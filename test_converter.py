import unittest
from decimal import Decimal as D
from converter import *

def line(account='606100',value='100',kind=' ',sub='',ref='1',source='1',plan='',dt='010126'):
    s=list(' '*199)
    for start,length,text in [(0,3,'AC'),(3,6,dt),(9,2,'FF'),(11,13,account),(24,1,kind),(25,13,sub),(38,13,ref),
                              (51,25,'Facture été'),(83,1,'D' if D(value)>=0 else 'C'),(84,20,f'{abs(D(value)):.2f}'),
                              (104,1,'N'),(105,7,source),(138,3,'EUR'),(164,10,plan)]:
        s[start:start+length]=text.ljust(length)
    return ''.join(s)
def dataset(*rows):return parse_pnm(('DEMO\r\n'+'\r\n'.join(rows)).encode('cp1252'))

class Tests(unittest.TestCase):
    def simple(self,allocations=None):
        return dataset(line(),*(allocations or []),line(account='401000',value='-100',kind='X',sub='401CLIENT',source='2'))
    def test_balanced(self):
        d=self.simple(); rows,rep,_=build_export(d,defaults(d)); self.assertEqual(len(rows),2);self.assertEqual(rep['debit'],'100,00')
    def test_multi_plan_no_double(self):
        d=self.simple([line(kind='A',sub='A',value='60',plan='1'),line(kind='A',sub='B',value='40',plan='1'),line(kind='A',sub='C',value='100',plan='2')])
        rows,_,_=build_export(d,defaults(d));self.assertEqual(len(rows),4)
        self.assertEqual(len({r['Identifiant de ligne'] for r in rows}),2)
        w=defaultdict(D)
        for r in rows:
            if r['Catégorie']:w[r['Famille de catégories']]+=D(r['Poids de la catégorie'].replace(',','.'))
        self.assertEqual(list(w.values()),[D(1),D(1)])
    def test_orphan(self):
        with self.assertRaises(ConversionError): dataset(line(kind='A',sub='A'))
    def test_mismatched_parent(self):
        with self.assertRaises(ConversionError):self.simple([line(kind='A',sub='A',source='99')])
    def test_partial_strict_and_remainder(self):
        d=self.simple([line(kind='A',sub='A',value='60')]); c=defaults(d)
        with self.assertRaises(ConversionError):build_export(d,c)
        c['policies']['2|1']='remainder';rows,_,_=build_export(d,c)
        self.assertIn('NON AFFECTÉ — REPRISE',[r['Catégorie'] for r in rows])
        self.assertEqual(rows[0]['Poids de la catégorie'],'0,600000000000')
    def test_normalization_opt_in(self):
        d=self.simple([line(kind='A',sub='A',value='200')]); c=defaults(d)
        c['policies']['2|1']='remainder'
        with self.assertRaises(ConversionError):build_export(d,c)
        c['policies']['2|1']='normalize';rows,_,_=build_export(d,c)
        self.assertEqual(rows[0]['Débit'],'100,00');self.assertEqual(D(rows[0]['Poids de la catégorie'].replace(',','.')),1)
    def test_correction(self):
        d=self.simple([line(kind='A',sub='A',value='200')]);c=defaults(d);c['overrides']['3']='100,00'
        self.assertEqual(analytic_issues(d,c['overrides']),[]);build_export(d,c)
    def test_credit_analytics(self):
        d=dataset(line(value='-100'),line(kind='A',sub='A',value='-100'),line(account='401000',value='100',source='2'))
        rows,_,_=build_export(d,defaults(d));self.assertEqual(rows[0]['Crédit'],'100,00')
    def test_unbalanced_month_blocks(self):
        d=dataset(line());c=defaults(d);c['group_month']=True
        with self.assertRaises(ConversionError):build_export(d,c)
    def test_group_requires_choice(self):
        d=dataset(line(),line(account='401000',value='-100',source='2',ref='2',dt='020126'));c=defaults(d)
        with self.assertRaises(ConversionError):build_export(d,c)
        c['group_month']=True;rows,report,_=build_export(d,c)
        self.assertEqual(rows[0]['Date'],'31/01/2026');self.assertEqual(rows[0]['Numéro de pièce'],rows[1]['Numéro de pièce']);self.assertEqual(report['pieces_regroupees'],2)
    def test_invalid_length(self):
        with self.assertRaises(ConversionError):parse_pnm(b'DEMO\nwrong')
    def test_no_silent_drop(self):
        with self.assertRaises(ConversionError):dataset(line(kind='E'))
    def test_encoding_and_header(self):
        d=self.simple();self.assertEqual(d.encoding,'cp1252');self.assertEqual(d.records[0].label,'Facture été')
    def test_merge_plans_blocks(self):
        d=self.simple([line(kind='A',sub='A',plan='1'),line(kind='A',sub='A',plan='2')]);c=defaults(d)
        for cat in c['categories'].values():cat['family']='Same'
        with self.assertRaises(ConversionError):build_export(d,c)
    def test_negative_weight_blocks(self):
        d=self.simple([line(kind='A',sub='A',value='120'),line(kind='A',sub='B',value='-20')])
        with self.assertRaises(ConversionError):build_export(d,defaults(d))
    def test_signed_adjustment_same_section(self):
        negative=line(kind='A',sub='A',value='0.02')
        negative=negative[:84]+'-0.02'.ljust(20)+negative[104:]
        d=self.simple([line(kind='A',sub='A',value='100.02'),negative])
        rows,_,_=build_export(d,defaults(d))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['Débit'],'100,00')
    def test_simulations_opt_in(self):
        raw=('DEMO\n'+'\n'.join(x[:104]+'S'+x[105:] for x in [line(),line(value='-100',account='401000',source='2')])).encode()
        with self.assertRaises(ConversionError):parse_pnm(raw)
        d=parse_pnm(raw,include_simulations=True)
        self.assertEqual(len(d.records),2)
        build_export(d,defaults(d))

if __name__=='__main__':unittest.main()
