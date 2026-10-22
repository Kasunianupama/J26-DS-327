"""Create a small native XLSX in memory from the validated displayed milk snapshot."""
from datetime import date
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree.ElementTree import Element, SubElement, tostring
from math import ceil
import re
from .milk_report import MilkReport, milk_explanation

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def tag(name):return '{'+NS+'}'+name


def sheet_xml(rows, widths, *, header_row, merges=(), narrative_rows=(), last_filter_row=None):
    """Typed cells only. Strings are inline text, never formulas or external links."""
    root=Element(tag('worksheet'))
    views=SubElement(root,tag('sheetViews'));view=SubElement(views,tag('sheetView'),workbookViewId='0',showGridLines='0')
    SubElement(view,tag('pane'),ySplit=str(header_row),topLeftCell=f'A{header_row+1}',activePane='bottomLeft',state='frozen')
    SubElement(root,tag('sheetFormatPr'),defaultRowHeight='22')
    columns=SubElement(root,tag('cols'))
    for index,width in enumerate(widths,1):
        SubElement(columns,tag('col'),min=str(index),max=str(index),width=str(width),customWidth='1')
    data=SubElement(root,tag('sheetData'))
    for index,values in enumerate(rows,1):
        attrs=dict(r=str(index))
        if index in narrative_rows:
            value=values[0][0] if isinstance(values[0],tuple) else values[0]
            glyph=9 if re.search('[\u0b80-\u0bff\u0d80-\u0dff]',str(value)) else 7
            height=max(32,min(320,ceil(len(str(value))*glyph/(sum(widths)*7))*18+14))
            attrs.update(ht=str(height),customHeight='1')
        if header_row==5 and index==10:attrs.update(ht='36',customHeight='1')
        if index==1:attrs.update(ht='32',customHeight='1')
        row=SubElement(data,tag('row'),attrs)
        for col,item in enumerate(values,1):
            value,style=item if isinstance(item,tuple) else (item,0)
            if value is None:continue
            ref=f'{chr(64+col)}{index}'
            if isinstance(value,date):
                cell=SubElement(row,tag('c'),r=ref,s='5')
                serial=(value-date(1899,12,30)).days
                if value<date(1900,3,1):serial-=1
                SubElement(cell,tag('v')).text=str(serial)
            elif isinstance(value,(int,float)) and not isinstance(value,bool):
                cell=SubElement(row,tag('c'),r=ref,s=str(style or 3))
                SubElement(cell,tag('v')).text=repr(value)
            else:
                cell=SubElement(row,tag('c'),r=ref,s=str(style),t='inlineStr')
                text=SubElement(SubElement(cell,tag('is')),tag('t'),{'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
                text.text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))
    if last_filter_row:
        SubElement(root,tag('autoFilter'),ref=f'A{header_row}:E{last_filter_row}')
    if merges:
        group=SubElement(root,tag('mergeCells'),count=str(len(merges)))
        for ref in merges:SubElement(group,tag('mergeCell'),ref=ref)
    SubElement(root,tag('pageMargins'),left='0.3',right='0.3',top='0.5',bottom='0.5',header='0.2',footer='0.2')
    SubElement(root,tag('pageSetup'),orientation='landscape',paperSize='9',fitToWidth='1',fitToHeight='0')
    return tostring(root,encoding='utf-8',xml_declaration=True)


STYLES='''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="3"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="0.00%"/><numFmt numFmtId="166" formatCode="yyyy-mm-dd"/></numFmts>
<fonts count="3"><font><sz val="11"/><name val="Nirmala UI"/><color rgb="FF243E35"/></font><font><b/><sz val="16"/><name val="Nirmala UI"/><color rgb="FFFFFFFF"/></font><font><b/><sz val="11"/><name val="Nirmala UI"/><color rgb="FF793F24"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF793F24"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF5EBE1"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="8">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFill="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''


def milk_workbook(report: MilkReport, language='en'):
    """The export is an immutable report snapshot; no formulas, macros or DB access."""
    report=MilkReport.model_validate(report.model_dump())
    def w(en,si,ta):return {'en':en,'si':si,'ta':ta}[language]
    missing=w('Not recorded','වාර්තා වී නැත','பதிவாகவில்லை')
    unavailable=w('Unavailable','ලබා ගත නොහැක','கிடைக்கவில்லை')
    d,s=report.sources['delpro'],report.sources['shipments']
    rows=[[(w('Farm X milk summary','Farm X කිරි සාරාංශය','Farm X பால் சுருக்கம்'),1),'',''],
          [w('Latest seven-day period','අවසන් දින හත','கடைசி ஏழு நாட்கள்'),report.days[7].date,report.observed_date],
          [w('Previous seven-day period','පෙර දින හත','முந்தைய ஏழு நாட்கள்'),report.days[0].date,report.days[6].date],[],
          [(w('Measure','මිනුම','அளவு'),2),('DelPro',2),(w('Milk shipments','කිරි නැව්ගත කිරීම්','பால் விநியோகம்'),2)],
          [w('Latest period milk (L)','අවසන් කාලයේ කිරි (L)','கடைசி காலத்தின் பால் (L)'),d.current_litres if d.current_litres is not None else missing,s.current_litres if s.current_litres is not None else missing],
          [w('Latest period records (days of 7)','අවසන් කාලයේ වාර්තාගත දින (7 න්)','கடைசி காலத்தின் பதிவான நாட்கள் (7 இல்)'),(d.current_observed_days,7),(s.current_observed_days,7)],
          [w('Previous period milk (L)','පෙර කාලයේ කිරි (L)','முந்தைய காலத்தின் பால் (L)'),d.previous_litres if d.previous_litres is not None else missing,s.previous_litres if s.previous_litres is not None else missing],
          [w('Previous period records (days of 7)','පෙර කාලයේ වාර්තාගත දින (7 න්)','முந்தைய காலத்தின் பதிவான நாட்கள் (7 இல்)'),(d.previous_observed_days,7),(s.previous_observed_days,7)],
          [w('Supported weekly change','ගණනය කළ හැකි සතිපතා වෙනස','கணக்கிடக்கூடிய வாராந்திர மாற்றம்'),(d.change_pct/100,4) if d.change_pct is not None else (unavailable,6),(s.change_pct/100,4) if s.change_pct is not None else (unavailable,6)],[]]
    merges=['A1:C1'];wrapped=[]
    for part in milk_explanation(report,language).split('\n\n'):
        heading,body=part.split('\n',1)
        rows.append([(heading.rstrip(':'),2),'','']);merges.append(f'A{len(rows)}:C{len(rows)}')
        rows.append([(body,6),'','']);merges.append(f'A{len(rows)}:C{len(rows)}');wrapped.append(len(rows))
    rows.extend([[],[(w('Source and original notes','මූලාශ්‍රය සහ මුල් සටහන්','மூலமும் அசல் குறிப்புகளும்'),2),'',''],
                 ['Source','core.herd_day',''],['Publication',report.core_version,''],['Records through',report.observed_date,'']])
    for note in report.warnings:
        rows.append([(note,6),'','']);merges.append(f'A{len(rows)}:C{len(rows)}');wrapped.append(len(rows))
    daily=[[(w('Farm X daily milk records','Farm X දෛනික කිරි වාර්තා','Farm X தினசரி பால் பதிவுகள்'),1),'','','',''],
           [('Daily herd-level totals. Missing measurements are blank; sources remain separate.',6),'','','',''],[],
           [(w('Date','දිනය','தேதி'),2),(w('Period','කාලය','காலம்'),2),('DelPro (L)',2),(w('Shipments (L)','නැව්ගත කිරීම් (L)','விநியோகம் (L)'),2),(w('Record status','වාර්තා තත්ත්වය','பதிவு நிலை'),2)]]
    for index,day in enumerate(report.days):
        status=w('Recorded','වාර්තාගත','பதிவாகியுள்ளது') if day.record_present else missing
        if day.record_present and day.data_gap is True:status=w('Data gap flagged','දත්ත හිඩැසක් සලකුණු කර ඇත','தரவு இடைவெளி குறிக்கப்பட்டுள்ளது')
        elif day.record_present and day.data_gap is None:status=w('Gap status unknown','හිඩැස් තත්ත්වය නොදනී','இடைவெளி நிலை தெரியவில்லை')
        daily.append([day.date,w('Previous','පෙර','முந்தைய') if index<7 else w('Latest','අවසන්','கடைசி'),day.delpro_litres,day.shipments_litres,status])
    daily.extend([[],[('Source: core.herd_day. Daily totals reconcile with the summary. DelPro zero cannot establish an observed day.',6),'','','','']])
    content_types='''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'''
    root_rels='''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
    workbook=f'''<workbook xmlns="{NS}" xmlns:r="{REL}"><sheets><sheet name="Summary" sheetId="1" r:id="rId1"/><sheet name="Daily records" sheetId="2" r:id="rId2"/></sheets></workbook>'''
    rels=f'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{REL}/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="{REL}/styles" Target="styles.xml"/></Relationships>'''
    buffer=BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as archive:
        for name,value in {'[Content_Types].xml':content_types,'_rels/.rels':root_rels,'xl/workbook.xml':workbook,'xl/_rels/workbook.xml.rels':rels,'xl/styles.xml':STYLES,
                           'xl/worksheets/sheet1.xml':sheet_xml(rows,[55,26,26],header_row=5,merges=merges,narrative_rows=wrapped),
                           'xl/worksheets/sheet2.xml':sheet_xml(daily,[16,16,20,22,46],header_row=4,merges=['A1:E1','A2:E2',f'A{len(daily)}:E{len(daily)}'],narrative_rows=[2,len(daily)],last_filter_row=18)}.items():
            archive.writestr(name,value)
    return buffer.getvalue()
