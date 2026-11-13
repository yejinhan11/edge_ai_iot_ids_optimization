"""Export the RF progress Markdown report to DOCX using only the standard library."""
import re
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'results/ciciot2023_rf_further/REPORT.md'
OUTPUT=ROOT/'results/reports/RF_추가경량화_진행보고.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def plain(text):
    return re.sub(r'\[([^]]+)\]\([^)]+\)',r'\1',text).replace('**','').replace('`','')


def paragraph(text,style=None):
    props=f'<w:pStyle w:val="{style}"/>' if style else ''
    return f'<w:p><w:pPr>{props}</w:pPr><w:r><w:t xml:space="preserve">{escape(plain(text))}</w:t></w:r></w:p>'


def table(rows):
    width=10000//len(rows[0])
    result=['<w:tbl><w:tblPr><w:tblW w:w="10000" w:type="dxa"/>'
        '<w:tblBorders>'+''.join(f'<w:{edge} w:val="single" w:sz="4" w:color="CBD5E1"/>' for edge in ['top','left','bottom','right','insideH','insideV'])+
        '</w:tblBorders></w:tblPr>']
    for i,row in enumerate(rows):
        result.append('<w:tr><w:trPr><w:cantSplit/>'+('<w:tblHeader/>' if i==0 else '')+'</w:trPr>')
        for cell in row:
            shading='<w:shd w:fill="E2E8F0"/>' if i==0 else ''
            result.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shading}</w:tcPr>{paragraph(cell,"TableText")}</w:tc>')
        result.append('</w:tr>')
    result.append('</w:tbl>')
    return ''.join(result)


def main():
    lines=SOURCE.read_text(encoding='utf-8').splitlines()
    body=[]; media=[]; pos=0
    while pos<len(lines):
        line=lines[pos]
        if line.startswith('|'):
            rows=[]
            while pos<len(lines) and lines[pos].startswith('|'):
                cells=[c.strip() for c in lines[pos].strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in cells): rows.append(cells)
                pos+=1
            body.append(table(rows)); continue
        match=re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)',line)
        if match:
            caption,filename=match.groups(); path=SOURCE.parent/filename
            if path.exists():
                image_id=len(media)+1; media.append(path)
                body.append(paragraph(caption,'Heading2'))
                body.append(f'<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="5700000" cy="3480000"/>'
                    f'<wp:docPr id="{image_id}" name="Figure {image_id}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                    f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{image_id}" name="{escape(path.name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
                    f'<pic:blipFill><a:blip r:embed="img{image_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                    '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="5700000" cy="3480000"/></a:xfrm>'
                    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
        elif line.startswith('# '): body.append(paragraph(line[2:],'Title'))
        elif line.startswith('## '): body.append(paragraph(line[3:],'Heading1'))
        elif line.startswith('### '): body.append(paragraph(line[4:],'Heading2'))
        elif line.strip(): body.append(paragraph(line))
        pos+=1
    document=(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>'+''.join(body)+
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="950" w:bottom="950" w:left="950" w:right="950"/></w:sectPr></w:body></w:document>')
    styles=f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:eastAsia="맑은 고딕"/><w:sz w:val="20"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="110"/></w:pPr></w:pPrDefault></w:docDefaults>'
    for name,size in [('Title',32),('Heading1',27),('Heading2',23),('TableText',17)]:
        bold='' if name=='TableText' else '<w:b/>'
        styles+=f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/><w:pPr><w:keepNext/></w:pPr><w:rPr>{bold}<w:sz w:val="{size}"/></w:rPr></w:style>'
    styles+='</w:styles>'
    content_types='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'
    relroot='http://schemas.openxmlformats.org/package/2006/relationships'
    reltype='http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    relationships=f'<Relationships xmlns="{relroot}"><Relationship Id="styles" Type="{reltype}styles" Target="styles.xml"/>'
    for i,path in enumerate(media,1): relationships+=f'<Relationship Id="img{i}" Type="{reltype}image" Target="media/{path.name}"/>'
    relationships+='</Relationships>'
    parts={'[Content_Types].xml':content_types,'word/document.xml':document,'word/styles.xml':styles,
        'word/_rels/document.xml.rels':relationships,
        '_rels/.rels':f'<Relationships xmlns="{relroot}"><Relationship Id="document" Type="{reltype}officeDocument" Target="word/document.xml"/></Relationships>'}
    for value in parts.values(): ElementTree.fromstring(value)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(OUTPUT,'w',ZIP_DEFLATED) as archive:
        for name,value in parts.items(): archive.writestr(name,value.encode('utf-8'))
        for path in media: archive.write(path,'word/media/'+path.name)
    with ZipFile(OUTPUT) as archive: assert archive.testzip() is None
    print(OUTPUT)


if __name__=='__main__': main()
