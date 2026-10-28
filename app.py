import json
import streamlit as st
import pandas as pd
from converter import (parse_pnm, defaults, balances, analytic_issues, build_export,
                       ConversionError, csv_bytes, money, IMPORT_HELP)

st.set_page_config(page_title='Sage → Pennylane • Analytique',page_icon='🔄',layout='wide')
st.markdown('''<style>.block-container{max-width:1350px;padding-top:2rem}h1{letter-spacing:-1px}
[data-testid="stMetric"]{background:#eef6f4;padding:15px;border-radius:12px}</style>''',unsafe_allow_html=True)
st.caption('REPRISE COMPTABLE · PNM SAGE · ANALYTIQUE CONSERVÉE')
st.title('Sage → Pennylane')
st.write('Convertissez les écritures et leurs ventilations analytiques en un import unique, avec une piste de contrôle.')

with st.sidebar:
    st.header('Fichier source')
    uploaded=st.file_uploader('Export trésorerie Sage',type=['pnm','txt'])
    headers=st.number_input('Nombre de lignes d’en-tête',min_value=0,max_value=100,value=1)
    encoding=st.selectbox('Encodage',['auto','cp1252','utf-8-sig','cp850','iso-8859-1'])
    include_simulations=st.checkbox('Inclure les écritures de simulation Sage (S)',value=False)
    saved=st.file_uploader('Recharger un paramétrage (facultatif)',type=['json'])
    st.caption('Traitement en mémoire. Aucun envoi à Pennylane. Le fichier reste sur la machine ou le serveur qui héberge cette application.')
    with st.expander('Mode d’emploi'):
        st.write('1. Chargez le PNM. 2. Vérifiez les correspondances. 3. Traitez les écarts. 4. Téléchargez le ZIP et importez le CSV dans Pennylane.')

if uploaded is None:
    st.info('Déposez votre fichier .pnm dans la barre latérale pour commencer.')
    st.markdown('**L’analytique est rattachée à chaque ligne comptable.** Les ventilations multi-sections sont exportées avec un identifiant commun et des poids pour éviter les doublons comptables.')
    st.stop()
try:
    data=parse_pnm(uploaded.getvalue(),encoding,int(headers),include_simulations)
except ConversionError as e:
    st.error(str(e)); st.stop()
config=defaults(data)
key=data.digest[:12]+f'-{headers}-{encoding}-{include_simulations}'
if saved:
    try:
        loaded=json.loads(saved.getvalue())
        if not isinstance(loaded,dict): raise ValueError('Objet JSON attendu.')
        for name in ['journals','categories','accounts','overrides','policies']:
            if name in loaded:
                if not isinstance(loaded[name],dict): raise ValueError(f'{name} doit être un objet.')
                config[name].update(loaded[name])
        config['group_month']=bool(loaded.get('group_month',False))
        key+='-'+__import__('hashlib').sha256(saved.getvalue()).hexdigest()[:8]
    except (ValueError,TypeError) as e: st.error(f'Paramétrage invalide : {e}');st.stop()

pieces,months=balances(data); issues=analytic_issues(data)
cols=st.columns(4)
cols[0].metric('Lignes comptables',f'{len(data.records):,}'.replace(',',' '))
cols[1].metric('Ventilations analytiques',f'{data.analytic_count:,}'.replace(',',' '))
cols[2].metric('Sections / plans',f'{len(config["categories"])} / {len({a.plan for r in data.records for a in r.allocations})}')
cols[3].metric('Écarts analytiques',len(issues))
st.caption(f'{data.company} · {data.encoding} · {headers} ligne(s) d’en-tête · {min(r.date for r in data.records):%d/%m/%Y} au {max(r.date for r in data.records):%d/%m/%Y}')
if data.excluded_simulations: st.info(f'{data.excluded_simulations} lignes de simulation Sage exclues. Activez l’option latérale pour les inclure.')
if include_simulations: st.warning('Les simulations incluses seront importées comme des écritures ordinaires dans Pennylane.')
total=sum(r.signed for r in data.records)
if total: st.error(f'Déséquilibre global : {money(total)} € — export bloqué.')
else: st.success(f'Comptabilité générale équilibrée : débit = crédit = {money(sum(max(r.signed,0) for r in data.records))} €.')

with st.expander('1 · Correspondance des journaux et des comptes',expanded=True):
    st.caption('Les journaux cibles doivent comporter 1 à 5 lettres. Les codes proposés sont à adapter aux journaux de votre dossier Pennylane.')
    jr=st.data_editor(pd.DataFrame([{'Journal Sage':j,'Journal Pennylane':v} for j,v in config['journals'].items()]),
                      disabled=['Journal Sage'],hide_index=True,key=key+'journals',width='stretch')
    config['journals']={str(r['Journal Sage']):str(r['Journal Pennylane'] or '').strip() for r in jr.to_dict('records')}
    st.caption('Auxiliaires : 401…/411… conservés dans le numéro de compte ; un préfixe est proposé si nécessaire. Aucun compte n’est fusionné automatiquement.')
    ac=st.data_editor(pd.DataFrame([{'Clé Sage':k,'Compte Pennylane':v} for k,v in config['accounts'].items()]),
                      disabled=['Clé Sage'],hide_index=True,key=key+'accounts',height=220,width='stretch')
    config['accounts']={str(r['Clé Sage']):str(r['Compte Pennylane'] or '').strip() for r in ac.to_dict('records')}
    counts={v:list(config['accounts'].values()).count(v) for v in set(config['accounts'].values())}
    collision=[v for v,n in counts.items() if n>1]
    if collision: st.warning('Plusieurs comptes source partagent un compte cible : '+', '.join(collision[:15]))

with st.expander('2 · Familles et catégories analytiques',expanded=True):
    st.caption('Le PNM contient les codes de section, sans leur intitulé complet. Remplacez « Plan 1 » et les codes par les noms exacts utilisés dans Pennylane, si ces catégories existent déjà. Un plan = une famille.')
    cat=st.data_editor(pd.DataFrame([{'Clé Sage':k,'Famille Pennylane':v['family'],'Catégorie Pennylane':v['category']} for k,v in config['categories'].items()],columns=['Clé Sage','Famille Pennylane','Catégorie Pennylane']),
                       disabled=['Clé Sage'],hide_index=True,key=key+'cats',height=260,width='stretch')
    config['categories']={str(r['Clé Sage']):{'family':str(r['Famille Pennylane'] or '').strip(),'category':str(r['Catégorie Pennylane'] or '').strip()} for r in cat.to_dict('records')}
    family_name=st.text_input('Renommer toute la famille du plan 1 (facultatif)',key=key+'family',placeholder='Exemple : Véhicules')
    if family_name.strip():
        for k,v in config['categories'].items():
            if k.split('|')[0]=='1':v['family']=family_name.strip()

with st.expander('3 · Écarts de ventilation analytique',expanded=bool(issues)):
    st.caption('Aucune modification automatique des montants comptables. Les corrections et choix sont enregistrés dans le rapport du ZIP.')
    if issues:
        st.warning(f'{len(issues)} ventilations ne totalisent pas le montant comptable d’origine.')
        st.dataframe(pd.DataFrame(issues),hide_index=True,width='stretch')
        st.download_button('Télécharger les écarts source',csv_bytes(issues),'ecarts_analytiques.csv',mime='text/csv')
        bad_lines={i['Ligne'] for i in issues}
        changes=[]
        for r in data.records:
            if r.line in bad_lines:
                for a in r.allocations:
                    changes.append({'Ligne analytique':a.line,'Ligne comptable':r.line,'Plan':a.plan,'Section':a.sub,
                                    'Montant signé Sage':money(a.signed),'Montant signé corrigé':str(config['overrides'].get(str(a.line),money(a.signed)))})
        ed=st.data_editor(pd.DataFrame(changes),disabled=['Ligne analytique','Ligne comptable','Plan','Section','Montant signé Sage'],
                          hide_index=True,key=key+'corrections',height=250,width='stretch')
        for r in ed.to_dict('records'): config['overrides'][str(r['Ligne analytique'])]=str(r['Montant signé corrigé'])
        names={'strict':'Bloquer tant que l’écart subsiste','remainder':'Affecter le reliquat à NON AFFECTÉ — REPRISE','normalize':'Recalculer proportionnellement à 100 %'}
        policy_rows=[{'Ligne comptable':i['Ligne'],'Plan':i['Plan'],'Traitement':names.get(config['policies'].get(f'{i["Ligne"]}|{i["Plan"]}','strict'),names['strict'])} for i in issues]
        pe=st.data_editor(pd.DataFrame(policy_rows),disabled=['Ligne comptable','Plan'],hide_index=True,key=key+'policies',
                          column_config={'Traitement':st.column_config.SelectboxColumn(options=list(names.values()),required=True)},width='stretch')
        reverse={v:k for k,v in names.items()}
        for r in pe.to_dict('records'): config['policies'][f'{r["Ligne comptable"]}|{r["Plan"]}']=reverse[r['Traitement']]
        st.caption('Reliquat : conserve les montants analytiques et complète une sous-ventilation. Proportionnel : modifie la répartition monétaire pour atteindre le montant comptable, y compris en surventilation. Vérifiez la cause avant de le choisir.')
    else: st.success('Toutes les ventilations totalisent leurs montants comptables.')

bad_pieces=[{'Pièce Sage':p,'Solde':money(v)} for p,v in pieces.items() if v]
with st.expander('4 · Équilibre des pièces',expanded=bool(bad_pieces)):
    if bad_pieces:
        st.warning(f'{len(bad_pieces)} pièces déséquilibrées sur la clé journal + date + référence.')
        st.dataframe(pd.DataFrame(bad_pieces),hide_index=True,height=200,width='stretch')
        st.download_button('Télécharger les pièces à contrôler',csv_bytes(bad_pieces),'pieces_a_controler.csv',mime='text/csv')
        config['group_month']=st.checkbox('Regrouper uniquement les pièces déséquilibrées par journal et par mois, avec date au dernier jour du mois',
                                         value=config['group_month'],key=key+'month')
        st.caption('Ce choix modifie les dates et références d’import des lignes concernées, ainsi que leur libellé de pièce. Les dates, références et libellés Sage restent dans la piste de contrôle. Pour conserver toutes les dates, corrigez les pièces dans Sage et réexportez.')
        if any(months.values()): st.error('Un journal mensuel reste déséquilibré : correction de la source indispensable.')
    else: st.success('Toutes les pièces sont équilibrées.')

st.subheader('5 · Télécharger l’import')
st.warning('L’import avec analytique remplace la reprise par FEC. Ne faites pas les deux : Pennylane créerait de nouvelles écritures en doublon.')
st.download_button('Sauvegarder le paramétrage',json.dumps(config,ensure_ascii=False,indent=2).encode(),'parametrage_sage_pennylane.json','application/json')
try:
    rows,report,package=build_export(data,config)
except (ConversionError,KeyError,TypeError) as e:
    st.error(f'Export bloqué : {e}')
else:
    st.caption(f'{report["lignes_csv"]} lignes CSV · {len(set(r["Identifiant de ligne"] for r in rows))} lignes comptables distinctes · 1 ligne d’en-tête.')
    st.dataframe(pd.DataFrame(rows[:100]),hide_index=True,width='stretch')
    ok=st.checkbox('J’ai vérifié les correspondances et les traitements choisis ; je confirme que cet import ne doublera pas une reprise déjà effectuée.',key=key+'review')
    st.download_button('Télécharger le ZIP d’import Pennylane',package,'import_pennylane_analytique.zip','application/zip',disabled=not ok,type='primary')
with st.expander('Consignes d’import et limites'):
    st.text(IMPORT_HELP)
    st.markdown('[Documentation Pennylane — import multi-analytique](https://help.pennylane.com/fr/articles/74963-importer-des-ecritures-comptables-avec-plusieurs-categories-analytiques)')
    st.caption('Formats PNM stricts : 105, 112, 138, 141, 164 et 199 caractères ; EUR uniquement. Échéances E et devises bloquées. Simulations exclues par défaut. Les champs non repris (mode de règlement, zones réservées) restent dans le fichier source. Aucun test d’import sur votre dossier Pennylane n’a été effectué.')
