"""Conversion PNM Sage → import Écritures Pennylane. Aucun appel réseau."""
from __future__ import annotations
import csv, io, re, json, hashlib, calendar
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from zipfile import ZipFile, ZIP_DEFLATED

D = Decimal
class ConversionError(ValueError): pass

def amount(value):
    try:
        n = D(str(value).strip().replace(' ', '').replace(',', '.'))
        if not n.is_finite() or n != n.quantize(D('.01')): raise ValueError()
        return n
    except (InvalidOperation, ValueError): raise ConversionError(f'Montant invalide : {value!r}')

def money(n): return format(n, '.2f').replace('.', ',')
def parse_date(s):
    try: return datetime.strptime(s, '%d%m%y').date()
    except ValueError: raise ConversionError(f'Date Sage invalide : {s!r}')

@dataclass
class Record:
    line: int
    journal: str
    date: date
    account: str
    kind: str
    sub: str
    ref: str
    label: str
    due: str
    signed: Decimal
    source_id: str
    plan: str
    status: str = 'N'
    allocations: list = field(default_factory=list)
    @property
    def uid(self): return f'L{self.line:07d}'
    @property
    def piece(self): return f'{self.journal}-{self.date:%Y%m%d}-{self.ref or "SANSREF"}'

@dataclass
class Dataset:
    company: str
    encoding: str
    digest: str
    records: list
    analytic_count: int
    headers: int
    excluded_simulations: int = 0

def parse_pnm(raw: bytes, encoding='auto', headers=1, include_simulations=False):
    if encoding == 'auto':
        try: text = raw.decode('utf-8-sig'); encoding = 'utf-8-sig'
        except UnicodeDecodeError:
            encoding = 'cp1252'
            try: text = raw.decode(encoding)
            except UnicodeDecodeError: raise ConversionError('Encodage non reconnu : choisissez CP850 ou ISO-8859-1.')
    else:
        try: text = raw.decode(encoding)
        except UnicodeDecodeError as e: raise ConversionError(str(e))
    lines = text.splitlines()
    if not 0 <= headers < len(lines): raise ConversionError('Nombre de lignes d’en-tête incorrect.')
    records = []; parent = None; analytic_count = 0
    for no, line in enumerate(lines[headers:], headers + 1):
        if not line.strip(): continue
        try:
            if len(line) not in (105,112,138,141,164,199):
                raise ConversionError(f'Longueur {len(line)} non prise en charge ; fichier à largeur fixe requis.')
            s = line.ljust(199)
            kind = s[24]
            if kind not in (' ', 'G', 'X', 'A'): raise ConversionError(f'Type {kind!r} non pris en charge (les échéances E doivent être traitées séparément).')
            if s[83] not in 'DC': raise ConversionError('Sens autre que D/C.')
            n = amount(s[84:104])
            if s[104] not in ('N','A','S',' '): raise ConversionError('Type d’écriture inconnu.')
            if s[138:141].strip() not in ('', 'EUR') or s[141:164].strip():
                raise ConversionError('Devises étrangères non prises en charge ; conversion EUR requise.')
            if s[174:].strip(): raise ConversionError('Extension de section analytique non prise en charge.')
            r = Record(no,s[:3].strip(),parse_date(s[3:9]),s[11:24].strip(),kind,
                       s[25:38].strip(),s[38:51].strip(),s[51:76].strip(),
                       parse_date(s[77:83]).strftime('%d/%m/%Y') if s[77:83].strip() else '',
                       n if s[83]=='D' else -n,s[105:112].strip(),s[164:174].strip() or '1')
            r.status=s[104]
            if not r.journal or not re.fullmatch(r'\d+',r.account): raise ConversionError('Journal absent ou compte général non numérique.')
            if kind == 'A':
                if parent is None: raise ConversionError('Ventilation orpheline.')
                if (r.journal,r.date,r.account,r.ref,r.source_id) != (parent.journal,parent.date,parent.account,parent.ref,parent.source_id):
                    raise ConversionError('La ventilation ne correspond pas à la ligne comptable précédente.')
                if not r.sub: raise ConversionError('Section analytique vide.')
                parent.allocations.append(r); analytic_count += 1
            else:
                if kind == 'X' and not r.sub: raise ConversionError('Auxiliaire vide.')
                records.append(r); parent = r
        except ConversionError as e: raise ConversionError(f'Ligne {no} : {e}')
    excluded=sum(r.status=='S' for r in records) if not include_simulations else 0
    if not include_simulations: records=[r for r in records if r.status!='S']
    analytic_count=sum(len(r.allocations) for r in records)
    if not records: raise ConversionError('Aucune ligne comptable hors exclusions.')
    return Dataset(lines[0].strip() if headers else '',encoding,hashlib.sha256(raw).hexdigest(),records,analytic_count,headers,excluded)

def analytic_issues(data, overrides=None):
    overrides = overrides or {}; issues=[]
    for r in data.records:
        groups=defaultdict(lambda: D(0))
        for a in r.allocations: groups[a.plan]+=amount(overrides.get(str(a.line),a.signed))
        for plan,total in groups.items():
            if total != r.signed:
                issues.append({'Ligne':r.line,'Identifiant Sage':r.source_id,'Pièce':r.piece,'Compte':r.account,'Libellé':r.label,
                               'Plan':plan,'Montant comptable':money(r.signed),'Total analytique':money(total),'Écart':money(r.signed-total)})
    return issues

def balances(data):
    pieces=defaultdict(lambda:D(0)); months=defaultdict(lambda:D(0))
    for r in data.records:
        pieces[r.piece]+=r.signed; months[f'{r.journal}-{r.date:%Y%m}']+=r.signed
    return pieces,months

def defaults(data):
    names={'10':'ODG','50':'BNP','51':'BQ','60':'ACH','70':'VTE'}
    journals={j:names.get(j,j if re.fullmatch('[A-Za-z]{1,5}',j) else 'J'+''.join(chr(65+int(c)) if c.isdigit() else c for c in j)) for j in sorted({r.journal for r in data.records})}
    cats={}
    accounts={}
    for r in data.records:
        key=f'{r.account}|{r.sub if r.kind=="X" else ""}'
        accounts[key]=r.sub if r.kind=='X' and r.sub.startswith(r.account[:3]) else (r.account[:3]+r.sub if r.kind=='X' else r.account)
        for a in r.allocations: cats[f'{a.plan}|{a.sub}']={'family':f'Plan {a.plan}','category':a.sub}
    return {'journals':journals,'categories':cats,'accounts':accounts,'overrides':{},'policies':{},'group_month':False}

def csv_bytes(rows, fields=None):
    out=io.StringIO(newline=''); rows=list(rows)
    fields=fields or (list(rows[0]) if rows else ['Information'])
    w=csv.DictWriter(out,fieldnames=fields,delimiter=';',lineterminator='\r\n');w.writeheader();w.writerows(rows)
    return out.getvalue().encode('utf-8-sig')

def build_export(data, config):
    """Strict by default. Policies per parent/plan: strict, remainder, normalize."""
    if sum(r.signed for r in data.records)!=0: raise ConversionError('Comptabilité générale déséquilibrée.')
    for j in {r.journal for r in data.records}:
        if not re.fullmatch('[A-Za-z]{1,5}',config['journals'].get(j,'')): raise ConversionError(f'Journal {j} : 1 à 5 lettres requises.')
    if len(set(config['journals'].values()))!=len(config['journals']): raise ConversionError('Deux journaux Sage ne peuvent pas partager le même code cible.')
    pieces,months=balances(data); bad={k for k,v in pieces.items() if v}
    if bad and not config.get('group_month'): raise ConversionError(f'{len(bad)} pièces déséquilibrées : corrigez la source ou choisissez le regroupement mensuel.')
    if any(months.values()): raise ConversionError('Au moins un journal mensuel est déséquilibré.')
    # Each Sage plan must remain a separate Pennylane family.
    family_plan={}; plan_family={}
    for r in data.records:
        for a in r.allocations:
            m=config['categories'].get(f'{a.plan}|{a.sub}',{})
            family=m.get('family','').strip(); category=m.get('category','').strip()
            if not family or not category: raise ConversionError(f'Famille/catégorie manquante : {a.plan}/{a.sub}.')
            if family in family_plan and family_plan[family]!=a.plan: raise ConversionError('Deux plans ne peuvent pas fusionner dans une même famille.')
            if a.plan in plan_family and plan_family[a.plan]!=family: raise ConversionError('Un plan doit correspondre à une seule famille.')
            family_plan[family]=a.plan;plan_family[a.plan]=family
    rows=[]; audit=[]; labels={}; zeros=0
    for r in data.records:
        account=config['accounts'].get(f'{r.account}|{r.sub if r.kind=="X" else ""}','')
        if not re.fullmatch(r'\d+|(?:401|411|410|421|455|467)[A-Za-z0-9]+',account): raise ConversionError(f'Compte Pennylane invalide : {account!r}.')
        if not r.signed:
            if r.allocations: raise ConversionError(f'Ligne {r.line} : ventilation sur montant nul.')
            zeros+=1; continue
        regrouped=r.piece in bad
        ref=f'REPRISE-{r.journal}-{r.date:%Y%m}' if regrouped else r.piece
        dt=r.date.replace(day=calendar.monthrange(r.date.year,r.date.month)[1]) if regrouped else r.date
        label=f'Reprise Sage {r.journal} {r.date:%m/%Y}' if regrouped else labels.setdefault(ref,r.label or ref)
        base={'Date':dt.strftime('%d/%m/%Y'),'Code journal':config['journals'][r.journal],
              'Numéro de pièce':ref,'Numéro de compte':account,'Libellé':label,
              'Débit':money(max(r.signed,D(0))),'Crédit':money(max(-r.signed,D(0))),
              'Date d’échéance':r.due,'Identifiant de ligne':r.uid,
              'Famille de catégories':'','Catégorie':'','Poids de la catégorie':''}
        groups=defaultdict(list)
        for a in r.allocations: groups[a.plan].append(a)
        if not groups: rows.append(base)
        for plan, allocations in groups.items():
            sums=defaultdict(lambda:D(0))
            for a in allocations:
                n=amount(config.get('overrides',{}).get(str(a.line),a.signed))
                m=config['categories'][f'{plan}|{a.sub}']; sums[(m['family'].strip(),m['category'].strip())]+=n
                audit.append({'Ligne comptable':r.line,'Ligne analytique':a.line,'ID export':r.uid,'Plan':plan,
                              'Section Sage':a.sub,'Montant Sage':money(a.signed),'Montant retenu':money(n),
                              'Traitement':config.get('policies',{}).get(f'{r.line}|{plan}','strict')})
            total=sum(sums.values()); policy=config.get('policies',{}).get(f'{r.line}|{plan}','strict')
            if total!=r.signed:
                if policy=='remainder':
                    rest=r.signed-total
                    if rest*r.signed<=0: raise ConversionError(f'Ligne {r.line} : reliquat impossible (surventilation).')
                    sums[(plan_family[plan],'NON AFFECTÉ — REPRISE')]+=rest; total=r.signed
                elif policy=='normalize':
                    if total*r.signed<=0: raise ConversionError(f'Ligne {r.line} : total analytique nul ou de sens contraire.')
                else: raise ConversionError(f'Ligne {r.line}, plan {plan} : ventilation {money(total)} ≠ comptabilité {money(r.signed)}.')
            nonzero=[(k,n) for k,n in sums.items() if n]
            if any(n*r.signed<0 for _,n in nonzero): raise ConversionError(f'Ligne {r.line} : ventilation de sens contraire ; correction manuelle requise.')
            weights=[(n/total).quantize(D('.000000000001')) for _,n in nonzero]
            if not weights: raise ConversionError(f'Ligne {r.line} : ventilation vide.')
            weights[-1]+=D(1)-sum(weights)
            for ((family,category),n),weight in zip(nonzero,weights):
                if not 0<weight<=1: raise ConversionError(f'Ligne {r.line} : poids analytique invalide.')
                rows.append(dict(base,**{'Famille de catégories':family,'Catégorie':category,'Poids de la catégorie':format(weight,'f').replace('.',',')}))
    trace=[{'Identifiant de ligne':r.uid,'Ligne PNM':r.line,'Identifiant Sage':r.source_id,'Journal Sage':r.journal,
            'Date Sage':r.date.strftime('%d/%m/%Y'),'Référence Sage':r.ref,'Compte général Sage':r.account,
            'Auxiliaire Sage':r.sub if r.kind=='X' else '', 'Libellé Sage':r.label,'Montant signé Sage':money(r.signed),
            'Type écriture Sage':r.status,'Regroupement mensuel':r.piece in bad} for r in data.records]
    report={'societe':data.company,'sha256_source':data.digest,'encodage':data.encoding,'lignes_entete_source':data.headers,
            'lignes_comptables':len(data.records),'lignes_simulation_exclues':data.excluded_simulations,'lignes_analytiques_source':data.analytic_count,'lignes_csv':len(rows),
            'debit':money(sum(max(r.signed,D(0)) for r in data.records)),
            'credit':money(sum(max(-r.signed,D(0)) for r in data.records)),
            'pieces_regroupees':len(bad),'lignes_montant_nul_non_exportees':zeros,'ecarts_analytiques_source':analytic_issues(data),
            'parametrage':config}
    out=io.BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        z.writestr('01_IMPORT_PENNYLANE.csv',csv_bytes(rows))
        z.writestr('02_PISTE_CONTROLE.csv',csv_bytes(trace))
        z.writestr('03_VENTILATIONS_CONTROLE.csv',csv_bytes(audit))
        z.writestr('04_RAPPORT.json',json.dumps(report,ensure_ascii=False,indent=2))
        z.writestr('05_PARAMETRAGE.json',json.dumps(config,ensure_ascii=False,indent=2))
        z.writestr('LIRE_AVANT_IMPORT.txt',IMPORT_HELP)
    return rows,report,out.getvalue()

IMPORT_HELP='''Importer uniquement 01_IMPORT_PENNYLANE.csv dans Saisie > Imports > Écritures.
Séparateur ; / UTF-8 / dates JJ/MM/AAAA / 1 ligne d’en-tête.
Mapper toutes les colonnes homonymes, notamment Identifiant de ligne, Famille de catégories,
Catégorie et Poids de la catégorie. Les montants répétés servent à porter les catégories :
ne jamais sommer le CSV sans dédupliquer les identifiants de ligne.
Le libellé exporté est commun à la pièce ; les libellés d’origine restent dans la piste de contrôle.
Les comptes auxiliaires sont dans Numéro de compte. Pas de colonne auxiliaire séparée.
Le code analytique optionnel n’est pas transmis : vérifier les noms des catégories existantes.
Ne pas importer aussi le FEC ou refaire cet import : cela créerait des doublons.
Si un FEC a déjà été importé, organiser la reprise avant de réimporter ces écritures.
Les lignes regroupées sont datées en fin de mois : voir Date Sage dans la piste de contrôle.
Un recalcul proportionnel change les montants analytiques, jamais les montants comptables.
Vérifier la balance, le grand livre analytique et quelques pièces après import.
Le convertisseur ne reprend ni lettrage ni pièces jointes et ne crée pas de transactions bancaires.
Aucun import réel dans Pennylane n’a été exécuté par cet outil.
'''
