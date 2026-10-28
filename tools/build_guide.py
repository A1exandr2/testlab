#!/usr/bin/env python3
"""Build the ЕСПД user/operator guide; retain genuine screenshots unchanged."""
from io import BytesIO
from pathlib import Path
import json
import os
import re
import cairo

TOOLS = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('TESTLAB_GUIDE_DIR', TOOLS.parent / 'docs' / 'user-guide' / 'generated')).expanduser().resolve()
ROOT.mkdir(parents=True, exist_ok=True)
CODE = 'ТЛ.00001-01 34 01'
DATE = '26.10.2026'
MM = 72/25.4
W,H = 210*MM,297*MM
LEFT,RIGHT,TOP,BOTTOM = 20*MM,10*MM,27*MM,15*MM
WIDTH = W-LEFT-RIGHT
FONT = 'Liberation Serif'
SIZE,LEADING = 12,18
INDENT = 12.5*MM
FIGURES = {
    'login': ('01-login.png', 'Форма входа в приложение'),
    'registration': ('02-registration.png', 'Форма регистрации пользователя'),
    'waiting': ('03-waiting.png', 'Начальный экран пользователя без групп'),
    'overview_admin': ('04-overview-admin.png', 'Рабочее окно администратора и сводка результатов'),
    'overview_user': ('06-overview-user.png', 'Рабочее окно обычного пользователя'),
    'new_group': ('07-new-group.png', 'Форма создания группы'),
    'overview_empty': ('05-overview-empty.png', 'Состояние новой группы без проверок'),
    'new_check': ('08-new-check.png', 'Форма создания проверки'),
    'checks': ('09-checks.png', 'Список проверок и элементы управления списком'),
    'filtered': ('10-filtered.png', 'Список проверок с фильтром результата «Ошибка»'),
    'result': ('11-result.png', 'Карточка проверки и форма сохранения результата'),
    'team_admin': ('12-team-admin.png', 'Список участников в окне администратора'),
    'add_member': ('13-add-member.png', 'Форма добавления зарегистрированного пользователя'),
    'team_user': ('14-team-user.png', 'Список участников в окне обычного пользователя'),
}
REFERENCES = [
    ('ГОСТ 19.505-79', 'Единая система программной документации. Руководство оператора. Требования к содержанию и оформлению',
     'https://protect.gost.ru/gost/details/07fec7b0-024f-407f-b5a8-7ebfe7cfa0a9'),
    ('ГОСТ 19.105-78', 'Единая система программной документации. Общие требования к программным документам',
     'https://protect.gost.ru/gost/details/500f8c05-0b04-40fc-a049-4212eae807c3'),
    ('ГОСТ 19.106-78', 'Единая система программной документации. Требования к программным документам, выполненным печатным способом',
     'https://protect.gost.ru/gost/details/237d9e0c-a8a8-40a2-a2f5-f8182da346a8'),
    ('ГОСТ 19.104-78', 'Единая система программной документации. Основные надписи',
     'https://protect.gost.ru/gost/details/b54b67fd-f44c-49da-a18a-2bda30cc3674'),
]
source = (TOOLS/'guide_source.md').read_text()
order = re.findall(r'\{\{figure:(\w+)\}\}',source)
assert len(order)==len(set(order))==14, 'Нужны 14 уникальных рисунков'
missing=[key for key in order if not (ROOT/'Скриншоты'/FIGURES[key][0]).is_file()]
if missing: raise SystemExit('Не найдены снимки: '+', '.join(missing))
figure_numbers={key:i+1 for i,key in enumerate(order)}
source=re.sub(r'\{\{ref:(\w+)\}\}',lambda m:str(figure_numbers[m[1]]),source)


def parse(text):
    blocks=[];lines=text.splitlines();i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('# '):i+=1;continue
        m=re.match(r'^(#{2,3})\s+(.+)',line)
        if m:blocks.append(('heading',len(m[1]),m[2]));i+=1;continue
        m=re.fullmatch(r'\{\{figure:(\w+)\}\}',line)
        if m:blocks.append(('figure',m[1]));i+=1;continue
        if line.startswith('Таблица '):
            caption=line;i+=1
            while i<len(lines) and not lines[i].strip():i+=1
            data=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[v.strip() for v in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',v) for v in cells):data.append(cells)
                i+=1
            blocks.append(('table',caption,data));continue
        m=re.match(r'^(\d+\))\s+(.+)',line)
        if m:blocks.append(('step',m[1],m[2]));i+=1;continue
        if line.startswith('- '):blocks.append(('step','–',line[2:]));i+=1;continue
        parts=[line];i+=1
        while i<len(lines) and lines[i].strip():
            candidate=lines[i].strip()
            if candidate.startswith(('#','{{figure:','Таблица ','- ')) or re.match(r'^\d+\)',candidate):break
            parts.append(candidate);i+=1
        blocks.append(('paragraph',' '.join(parts)))
    return blocks

blocks=parse(source)
heads=[b[2] for b in blocks if b[0]=='heading']
TOC_TITLES = [h for h in heads if h!='АННОТАЦИЯ']+['Перечень рисунков','Перечень ссылочных документов','Лист регистрации изменений']


class Layout:
    def __init__(self,target,toc_pages=None,total=None,draw_outlines=False):
        self.surface=cairo.PDFSurface(target,W,H)
        self.surface.set_metadata(cairo.PDF_METADATA_TITLE,'ТестЛаб. Руководство пользователя (руководство оператора)')
        self.surface.set_metadata(cairo.PDF_METADATA_SUBJECT,'ЕСПД; ГОСТ 19.505-79, ГОСТ 19.104-78, ГОСТ 19.105-78, ГОСТ 19.106-78')
        self.ctx=cairo.Context(self.surface)
        self.y=TOP;self.page=1;self.pages={};self.fig_pages={}
        self.toc_pages=toc_pages or {};self.total=total;self.outlines=draw_outlines
        self.max_used_y=0;self.overflows=[];self.tables=[]

    def font(self,size=SIZE,bold=False):
        self.ctx.select_font_face(FONT,cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        self.ctx.set_font_size(size)
        self.ctx.set_source_rgb(0,0,0)

    def tw(self,text,size=SIZE,bold=False):
        self.font(size,bold)
        return self.ctx.text_extents(text).x_advance

    def text(self,x,y,text,size=SIZE,bold=False):
        self.font(size,bold);self.ctx.move_to(x,y);self.ctx.show_text(text)

    def center(self,text,y,size=SIZE,bold=False):
        self.text(LEFT+(WIDTH-self.tw(text,size,bold))/2,y,text,size,bold)

    def header(self):
        if self.page==1:return
        self.center(str(self.page),13*MM,11)
        self.center(CODE,20*MM,10)

    def new_page(self):
        self.surface.show_page();self.page+=1;self.y=TOP;self.header()

    def fresh(self):
        if self.y>TOP+1:self.new_page()

    def need(self,height):
        if self.y+height>H-BOTTOM:self.new_page()

    def words(self,value):
        bold=False;end=0;words=[]
        for match in re.finditer(r'\*\*|[^\s*]+',value):
            if match[0]=='**':bold=not bold;continue
            space=bool(words) and bool(re.search(r'\s',value[end:match.start()]))
            words.append((match[0],bold,space));end=match.end()
        return words

    def lines(self,value,maxwidth,size=SIZE,firstwidth=None):
        result=[];line=[];used=0;limit=firstwidth or maxwidth
        tokens=self.words(value)
        for token_index,(token,bold,space) in enumerate(tokens):
            gap=self.tw(' ',size) if line and space else 0
            length=self.tw(token,size,bold)
            suffix=0
            for following,following_bold,following_space in tokens[token_index+1:]:
                if following_space:break
                suffix+=self.tw(following,size,following_bold)
            if line and used+gap+length+suffix>limit and space:
                result.append(line);line=[];used=0;gap=0;limit=maxwidth
            while length>limit:
                # Split a long URL/address without allowing text outside the margin.
                count=1
                while count<len(token) and self.tw(token[:count+1],size,bold)<=limit-used-gap:count+=1
                line.append((token[:count],bold,gap));result.append(line)
                token=token[count:];line=[];used=0;gap=0;limit=maxwidth
                length=self.tw(token,size,bold)
            line.append((token,bold,gap));used+=gap+length
        if line:result.append(line)
        return result or [[]]

    def line(self,words,x,baseline,size=SIZE,width=None,justify=False):
        actual=sum(self.tw(word,size,bold)+gap for word,bold,gap in words)
        gaps=sum(bool(gap) for _,_,gap in words)
        extra=(width-actual)/gaps if justify and gaps and width and width>actual else 0
        for word,bold,gap in words:
            x+=gap+(extra if gap else 0)
            self.text(x,baseline,word,size,bold);x+=self.tw(word,size,bold)
        if x>W-RIGHT+.5:self.overflows.append((self.page,'horizontal',round(x,2)))

    def paragraph(self,value,indent=True,size=SIZE,leading=LEADING,after=5,justify=True):
        first=INDENT if indent else 0
        lines=self.lines(value,WIDTH,size,WIDTH-first)
        if len(lines)<=4:self.need(len(lines)*leading+after)
        elif H-BOTTOM-self.y<leading*2:self.new_page()
        for index,row in enumerate(lines):
            if H-BOTTOM-self.y<leading:self.new_page()
            x=LEFT+(first if index==0 else 0)
            self.line(row,x,self.y+size,size,WIDTH-(first if index==0 else 0),justify and index<len(lines)-1)
            self.y+=leading
        self.y+=after
        self.max_used_y=max(self.max_used_y,self.y)

    def heading(self,value,level=2):
        major=level==2
        if major:self.fresh()
        else:
            self.need(34+18+29+36)
            self.y+=34
        self.pages[value]=self.page
        if self.outlines:
            if major:
                self.section_outline=self.surface.add_outline(cairo.PDF_OUTLINE_ROOT,value,f'page={self.page}',0)
            else:
                self.surface.add_outline(self.section_outline,value,f'page={self.page}',0)
        title=value.upper() if major else value
        if major:
            self.center(title,self.y+SIZE,SIZE,True)
        else:
            self.text(LEFT+INDENT,self.y+SIZE,title,SIZE,True)
            if LEFT+INDENT+self.tw(title,SIZE,True)>W-RIGHT:
                raise ValueError('Слишком длинный заголовок: '+title)
        self.y+=SIZE+29

    def steps(self,marker,value):
        prefix=marker+' '
        prefix_w=self.tw(prefix)
        x=LEFT+INDENT
        lines=self.lines(value,WIDTH-INDENT-prefix_w)
        if len(lines)<=4:self.need(len(lines)*LEADING+3)
        for index,line in enumerate(lines):
            self.need(LEADING)
            if index==0:self.text(x,self.y+SIZE,prefix)
            self.line(line,x+prefix_w,self.y+SIZE,SIZE,WIDTH-INDENT-prefix_w,index<len(lines)-1)
            self.y+=LEADING
        self.y+=3

    def table(self,caption,data):
        if not data:raise ValueError('Нет строк таблицы: '+caption)
        columns=len(data[0])
        widths=[WIDTH*.46,WIDTH*.54] if columns==2 else [WIDTH*.66,WIDTH*.17,WIDTH*.17]
        size=10.5;leading=14
        layouts=[]
        for row_index,row in enumerate(data):
            cells=[self.lines('**'+cell+'**' if row_index==0 else cell,width-12,size) for cell,width in zip(row,widths)]
            layouts.append((cells,max(len(cell) for cell in cells)*leading+12))
        number=caption.split(' — ',1)[0]
        title=caption.split(' — ',1)[1]
        def table_header(continuation=False):
            self.need(24+layouts[0][1]+layouts[min(1,len(layouts)-1)][1])
            self.text(W-RIGHT-self.tw(('Продолжение таблицы '+number.split()[-1]) if continuation else number,11),self.y+11,
                      ('Продолжение таблицы '+number.split()[-1]) if continuation else number,11)
            self.y+=17
            if not continuation:
                for titleline in self.lines(title,WIDTH,11):
                    plain=''.join((' ' if gap else '')+text for text,_,gap in titleline)
                    self.center(plain,self.y+11,11,True);self.y+=16
            draw_row(*layouts[0],header=True)
        def draw_row(cells,height,header=False):
            x=LEFT
            for lines,width in zip(cells,widths):
                self.ctx.set_line_width(.5);self.ctx.rectangle(x,self.y,width,height);self.ctx.stroke()
                for index,line in enumerate(lines):
                    if header:line=[(text,True,gap) for text,_,gap in line]
                    self.line(line,x+6,self.y+11+index*leading,size)
                x+=width
            self.y+=height
        self.need(55+layouts[0][1]+layouts[min(1,len(layouts)-1)][1])
        table_header()
        for cells,height in layouts[1:]:
            if self.y+height>H-BOTTOM:
                self.new_page();table_header(True)
            draw_row(cells,height)
        self.y+=14
        self.tables.append((caption,len(data)-1))

    def figure(self,key):
        filename,title=FIGURES[key]
        image=cairo.ImageSurface.create_from_png(str(ROOT/'Скриншоты'/filename))
        height=image.get_height()*WIDTH/image.get_width()
        size=11
        titlelines=self.lines(title,WIDTH,size)
        needed=len(titlelines)*16+height+27
        self.need(needed)
        self.fig_pages[key]=self.page
        for row in titlelines:
            plain=''.join((' ' if gap else '')+text for text,_,gap in row)
            self.center(plain,self.y+size,size,True);self.y+=16
        self.ctx.save();self.ctx.translate(LEFT,self.y)
        ratio=WIDTH/image.get_width();self.ctx.scale(ratio,ratio)
        self.ctx.set_source_surface(image);self.ctx.paint();self.ctx.restore()
        self.ctx.set_source_rgb(0,0,0);self.ctx.set_line_width(.4)
        self.ctx.rectangle(LEFT,self.y,WIDTH,height);self.ctx.stroke()
        self.y+=height+17
        self.center('Рис. '+str(figure_numbers[key]),self.y,11)
        self.y+=15

    def title(self):
        self.center('_______________________________',32*MM,12)
        self.center('(наименование организации)',39*MM,10)
        self.text(LEFT+WIDTH*.56,63*MM,'Лист утверждения',11)
        self.text(LEFT+WIDTH*.56,70*MM,CODE+'-ЛУ',10)
        self.center('ПРИЛОЖЕНИЕ СОВМЕСТНОЙ ПРОВЕРКИ ПРОЕКТОВ',105*MM,13,True)
        self.center('«ТЕСТЛАБ»',117*MM,18,True)
        self.center('РУКОВОДСТВО ПОЛЬЗОВАТЕЛЯ',141*MM,14,True)
        self.center('(Руководство оператора)',151*MM,12)
        self.center(CODE,170*MM,13)
        self.center('Редакция программы 2.0',184*MM,12)
        self.center('Листов '+str(self.total or '___'),197*MM,12)
        self.center('2026',274*MM,12)
        self.y=H-BOTTOM

    def contents(self):
        self.fresh();self.center('СОДЕРЖАНИЕ',self.y+SIZE,SIZE,True);self.y+=SIZE+29
        for title in TOC_TITLES:
            label=re.sub(r'^(\d+\.\s+)(.*)',lambda m:m[1]+m[2].capitalize(),title) if re.match(r'^\d+\.',title) else title
            # Preserve the case of product/UI names in subsection titles.
            if re.match(r'^\d+\.\d+',title):label=title
            indent=14 if re.match(r'^\d+\.\d+',title) else 0
            rows=self.lines(label,WIDTH-indent-30,11)
            self.need(len(rows)*16+6)
            dest=self.toc_pages.get(title,0)
            if dest:self.ctx.tag_begin(cairo.TAG_LINK,f'page={dest}')
            for index,row in enumerate(rows):
                self.line(row,LEFT+indent,self.y+11,11)
                if index==len(rows)-1:
                    end=LEFT+indent+sum(self.tw(t,11,b)+gap for t,b,gap in row)
                    lastx=W-RIGHT-26
                    x=end+8
                    while x<lastx:self.text(x,self.y+11,'.',10);x+=5
                    page_text=str(dest) if dest else '—'
                    self.text(W-RIGHT-self.tw(page_text,11),self.y+11,page_text,11)
                self.y+=16
            if dest:self.ctx.tag_end(cairo.TAG_LINK)
            self.y+=4

    def figures_index(self):
        self.heading('Перечень рисунков')
        for key in order:
            self.paragraph(f'Рис. {figure_numbers[key]} — {FIGURES[key][1]}. Лист {self.fig_pages[key]}.',False,11,16,8,False)

    def references(self):
        self.heading('Перечень ссылочных документов')
        for index,(code,title,url) in enumerate(REFERENCES,1):
            self.paragraph(f'{index}. **{code}**. {title}.',False)
            self.ctx.tag_begin(cairo.TAG_LINK,"uri='"+url+"'")
            self.paragraph(url,False,10,14,7,False)
            self.ctx.tag_end(cairo.TAG_LINK)
        self.paragraph('Источник сведений о статусе стандартов — официальный портал Росстандарта. Дата обращения: '+DATE+'.',False,11,16)

    def changes(self):
        self.heading('Лист регистрации изменений')
        widths=[9,17,17,15,19,23,20,27,17,16]
        factor=WIDTH/sum(widths);widths=[value*factor for value in widths]
        labels=['Изм.','Изменён-\nных','Заменён-\nных','Новых','Аннули-\nрованных','Всего\nлистов\nв докум.','№\nдоку-\nмента','Входящий №\nсопровод.\nдокумента\nи дата','Подпись','Дата']
        groupheight=24;headheight=58;start=self.y
        x=LEFT
        self.ctx.set_line_width(.5)
        # Four central columns share a group heading.
        groupx=LEFT+widths[0];groupw=sum(widths[1:5])
        self.ctx.rectangle(groupx,start,groupw,groupheight);self.ctx.stroke()
        self.text(groupx+(groupw-self.tw('Номера листов',9))/2,start+15,'Номера листов',9)
        for index,(width,label) in enumerate(zip(widths,labels)):
            yy=start+groupheight if 1<=index<=4 else start
            hh=headheight if 1<=index<=4 else headheight+groupheight
            self.ctx.rectangle(x,yy,width,hh);self.ctx.stroke()
            for n,line in enumerate(label.split('\n')):
                self.text(x+(width-self.tw(line,8))/2,yy+14+n*11,line,8)
            x+=width
        row_y=start+headheight+groupheight
        while row_y+24<=H-BOTTOM:
            x=LEFT
            for width in widths:self.ctx.rectangle(x,row_y,width,24);self.ctx.stroke();x+=width
            row_y+=24
        self.y=row_y

    def render(self):
        self.title();self.new_page()
        annotation=True
        for block in blocks:
            if block[0]=='heading' and block[2].startswith('1. '):
                self.contents();annotation=False
            if block[0]=='heading':self.heading(block[2],block[1])
            elif block[0]=='paragraph':self.paragraph(block[1])
            elif block[0]=='step':self.steps(block[1],block[2])
            elif block[0]=='figure':self.figure(block[1])
            elif block[0]=='table':self.table(block[1],block[2])
        self.figures_index();self.references();self.changes()
        self.surface.finish()
        return self


def approval(total):
    target=ROOT/'Лист утверждения.pdf'
    s=cairo.PDFSurface(str(target),W,H);c=cairo.Context(s)
    def t(x,y,value,size=12,bold=False):
        c.select_font_face(FONT,cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size);c.move_to(x,y);c.show_text(value)
    def center(y,value,size=12,bold=False):
        c.select_font_face(FONT,cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size);tw=c.text_extents(value).x_advance;t(LEFT+(WIDTH-tw)/2,y,value,size,bold)
    center(30*MM,'_______________________________')
    center(37*MM,'(наименование организации)',10)
    for x,label in [(LEFT,'СОГЛАСОВАНО'),(LEFT+100*MM,'УТВЕРЖДАЮ')]:
        t(x,57*MM,label,12,True)
        t(x,70*MM,'_______________________')
        t(x,77*MM,'(должность)',9)
        t(x,88*MM,'___________ /____________/')
        t(x,99*MM,'«___» __________ 2026 г.')
    center(125*MM,'ПРИЛОЖЕНИЕ СОВМЕСТНОЙ ПРОВЕРКИ ПРОЕКТОВ',13,True)
    center(136*MM,'«ТЕСТЛАБ»',16,True)
    center(150*MM,'РУКОВОДСТВО ПОЛЬЗОВАТЕЛЯ',13,True)
    center(159*MM,'(Руководство оператора)')
    center(174*MM,'ЛИСТ УТВЕРЖДЕНИЯ',13,True)
    center(184*MM,CODE+'-ЛУ')
    center(196*MM,f'Объём документа — {total} листов. Листов утверждения — 1.',11)
    t(LEFT,219*MM,'Разработал __________________ /________________/   Дата __________',11)
    t(LEFT,236*MM,'Нормоконтроль _______________ /________________/   Дата __________',11)
    center(276*MM,'2026')
    s.finish()


first=Layout(BytesIO()).render()
second=Layout(BytesIO(),first.pages,first.page).render()
assert first.pages==second.pages and first.page==second.page,'Нестабильное содержание'
output=ROOT/'Руководство пользователя.pdf'
final=Layout(str(output),second.pages,second.page,True).render()
assert not final.overflows,final.overflows
approval(final.page)

# Export an editable text source with the same section/figure numbering.
md=source
for key in order:
    filename,title=FIGURES[key]
    md=md.replace('{{figure:'+key+'}}',f'**{title}**\n\n![{title}](Скриншоты/{filename})\n\nРис. {figure_numbers[key]}')
contents='## СОДЕРЖАНИЕ\n\n'+'\n'.join(f'- {title} — с. {final.pages[title]}' for title in TOC_TITLES)+'\n\n'
md=md.replace('## 1. НАЗНАЧЕНИЕ ПРОГРАММЫ',contents+'## 1. НАЗНАЧЕНИЕ ПРОГРАММЫ',1)
md+='\n\n## ПЕРЕЧЕНЬ РИСУНКОВ\n\n'+'\n'.join(f'- Рис. {figure_numbers[key]} — {FIGURES[key][1]}. Лист {final.fig_pages[key]}.' for key in order)
md+='\n\n## ПЕРЕЧЕНЬ ССЫЛОЧНЫХ ДОКУМЕНТОВ\n\n'+'\n\n'.join(f'{i}. [{code}. {title}]({url})' for i,(code,title,url) in enumerate(REFERENCES,1))
md+='\n\n## ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ\n\nФорма для заполнения приведена в PDF.\n'
(ROOT/'Руководство пользователя.md').write_text(md)
report={'pdf':str(output),'pages':final.page,'screenshots':len(order),'included':order,'missing':[],
        'sections':final.pages,'figure_pages':final.fig_pages,'tables':len(final.tables),
        'format':{'page':'A4','margins_mm':{'left':20,'right':10,'top':27,'bottom':15},
                  'font':FONT,'text_pt':SIZE,'line_spacing_pt':LEADING},
        'approval_pdf':str(ROOT/'Лист утверждения.pdf')}
(ROOT/'build-status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
