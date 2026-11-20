
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import Rectangle, FancyBboxPatch, FancyArrowPatch, Patch
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator, FormatStrFormatter

work = Path(__file__).parent
original = work / 'original'
target = work.parent / 'figures'
(work.parent.parent / 'figure-preview-color').mkdir(exist_ok=True)
ink, mid, light, grid, pale = '#253442', '#526473', '#98A7B2', '#E0E7EB', '#F1F5F6'
blue, rust, teal, gold = '#246A9B', '#AD523A', '#28776D', '#BE8B35'
blue_tint, rust_tint, teal_tint = '#E5EFF6', '#F7EAE5', '#E5F2EE'
for p in [Path(r'C:\Windows\Fonts\msyh.ttc'), Path(r'C:\Windows\Fonts\msyhbd.ttc')]:
    if p.exists():
        fm.fontManager.addfont(p)
plt.rcParams.update({
    'font.family': ['Microsoft YaHei', 'DejaVu Sans'],
    'font.size': 9, 'text.color': ink, 'axes.labelcolor': ink,
    'axes.edgecolor': mid, 'axes.linewidth': 0.55, 'axes.titlesize': 10.3,
    'axes.titleweight': 'bold', 'xtick.color': mid, 'ytick.color': mid,
    'xtick.labelsize': 8.2, 'ytick.labelsize': 8.2,
    'grid.color': grid, 'grid.linewidth': 0.55, 'axes.axisbelow': True,
    'legend.frameon': False, 'legend.fontsize': 8.0,
    'pdf.fonttype': 42, 'ps.fonttype': 42, 'hatch.linewidth': .55,
    'axes.unicode_minus': False
})

def save(fig, index):
    fig.savefig(target/f'fig{index:02}.pdf', bbox_inches='tight', pad_inches=.085)
    fig.savefig((work.parent.parent / 'figure-preview-color')/f'fig{index:02}.png', dpi=145, bbox_inches='tight', pad_inches=.085)
    plt.close(fig)

def chart(ax, title='', x='', y='', gridaxis='y'):
    ax.spines[['top','right']].set_visible(False)
    ax.tick_params(length=2.8, pad=3)
    if gridaxis != "none": ax.grid(axis=gridaxis)
    if title: ax.set_title(title, loc='left', pad=9)
    if x: ax.set_xlabel(x)
    if y: ax.set_ylabel(y)

def diagram(w=7.0,h=3.0):
    f, ax=plt.subplots(figsize=(w,h))
    ax.set(xlim=(0,1),ylim=(0,1))
    ax.set_position([.015,.025,.97,.95])
    ax.axis('off')
    return f,ax

def box(ax, x, y, w, h, title, text='', fill=pale):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.005,rounding_size=0.014',fc=fill,ec=mid,lw=.8))
    ax.text(x+w/2, y+h*(.65 if text else .5),title,ha='center',va='center',weight='bold',fontsize=9.5)
    if text: ax.text(x+w/2,y+h*.26,text,ha='center',va='center',fontsize=7.2,color=mid)

def arrow(ax, a,b, style='-|>', ls='-',color=mid,**kw):
    ax.add_patch(FancyArrowPatch(a,b,arrowstyle=style,mutation_scale=9,lw=.9,linestyle=ls,color=color,**kw))

def annotate(ax, x,y, text, size=8.0, **kw): ax.text(x,y,text,fontsize=size,**kw)

def note(fig, msg, y=.01):
    fig.text(.5,y,msg,ha='center',va='bottom',color=mid,fontsize=8.0)

def panels():
    fig, axs=plt.subplots(1,2,figsize=(7.3,3.35),layout='constrained')
    return fig,axs

def bars(ax,x,y,width=.35,gray='.75',hatch=None,label=None):
    return ax.bar(x,y,width,color=gray,edgecolor=ink,linewidth=.6,hatch=hatch,label=label,zorder=2)

def fig01():
    fig,ax=plt.subplots(figsize=(7.45,3.22),layout='constrained')
    chart(ax,x='场地横坐标 x / m',y='场地纵坐标 y / m',gridaxis='both')
    ax.set(xlim=(-.5,10.25),ylim=(-2.32,3.67),xticks=range(9),yticks=range(-2,4))
    ax.add_patch(Rectangle((1.9,-.51),3.2,1.02,facecolor=blue_tint,edgecolor='none',zorder=1))
    ax.hlines([-.51,.51],1.9,5.1,color=ink,lw=1.55)
    ax.plot([1.45,5.6],[0,0],':',color=mid,lw=.75)
    ax.text(3.5,-.16,'共享通道',ha='center',va='center',weight='bold')
    ax.annotate('导轨内侧约 1.02 m',(3.5,.51),xytext=(3.5,1.13),ha='center',
                arrowprops=dict(arrowstyle='-',color=mid,lw=.65),fontsize=8)
    entries=[
        (.5,0,'B1 起点','o',(-8,-15),'right'),(.96,0,'蓝方第二批交付','o',(1,-29),'left'),
        (1.45,0,'西侧对准点','D',(-2,13),'center'),(5.60,0,'东侧对准点','D',(0,-20),'center'),
        (1.33,.88,'红方第一批交付','^',(0,10),'center'),(1.20,-1.83,'R2 取货','^',(8,0),'left'),
        (6.04,.80,'红方第二批交付','^',(8,3),'left'),(8,1.62,'B2 起点','o',(8,0),'left'),
        (8,2.41,'蓝方第一批交付','o',(8,0),'left'),(8,3.20,'R1 东侧折返','^',(8,0),'left')]
    for x,y,label,m,ofs,ha in entries:
        ax.scatter(x,y,marker=m,s=28,fc=blue if m=='o' else 'white',ec={'o':blue,'^':rust,'D':teal}[m],lw=.9,zorder=3)
        ax.annotate(label,(x,y),xytext=ofs,textcoords='offset points',ha=ha,va='center',fontsize=8)
    ax.legend(handles=[Line2D([],[],ls='',marker=m,ms=5,mec={'o':blue,'^':rust,'D':teal}[m],mfc=blue if m=='o' else 'white',label=l)
                       for m,l in [('o','蓝方'),('^','红方'),('D','对准点')]],
              loc='lower right',ncol=3)
    save(fig,1)

def fig02():
    f,a=diagram(h=2.48)
    box(a,.02,.65,.24,.28,'任务卡与观察','释放时间、期限、相机帧')
    box(a,.38,.65,.24,.28,'队伍协调','判断报告时效与通道状态',fill=blue_tint)
    box(a,.74,.65,.24,.28,'车辆与无人机','执行路线、运输与观察')
    box(a,.38,.06,.24,.28,'裁判记录与验收','车体净空、停车与交付')
    arrow(a,(.26,.78),(.38,.78))
    arrow(a,(.62,.78),(.74,.78))
    annotate(a,.32,.84,'任务与时效',7.2,ha='center',color=mid)
    annotate(a,.68,.84,'放行与目标点',7.2,ha='center',color=mid)
    a.plot([.86,.86],[.65,.20],c=mid,lw=.9)
    arrow(a,(.86,.20),(.62,.20))
    annotate(a,.76,.26,'实际位置与任务事件',7.3,ha='center',color=mid)
    arrow(a,(.50,.34),(.50,.65))
    annotate(a,.51,.46,'占用与完成状态',7.3,ha='left',color=mid)
    save(f,2)

def fig03():
    im=Image.open(original/'fig03.jpg').convert('RGB')
    fig,axs=plt.subplots(1,2,figsize=(6.5,2.45))
    fig.subplots_adjust(left=.03,right=.97,top=.89,bottom=.1,wspace=.08)
    for ax,crop,title,sub in zip(axs,[(55,14,535,374),(565,14,1045,374)],
        ['(a) 工位可见','(b) 工位遮挡'],['标记可见，发出观察报告','标记未检出，未发出报告']):
        ax.imshow(im.crop(crop),interpolation='nearest')
        ax.set_title(title,loc='left',pad=5)
        ax.axis('off')
        ax.text(.5,-.08,sub,ha='center',va='top',transform=ax.transAxes,fontsize=8,color=mid)
    save(fig,3)

def fig04():
    f,a=diagram(h=2.62)
    box(a,.025,.49,.14,.21,'车辆接近区')
    a.add_patch(Rectangle((.21,.48),.47,.24,fc=blue_tint,ec=mid,lw=.9))
    a.text(.37,.6,'通道占用区',ha='center',va='center')
    box(a,.81,.76,.15,.15,'东口泊位 1')
    box(a,.81,.28,.15,.15,'东口泊位 2')
    arrow(a,(.165,.60),(.26,.60))
    arrow(a,(.58,.60),(.76,.60))
    a.plot([.51,.875],[.87,.43],ls='--',color=mid,lw=1.05)
    a.scatter([.61],[.60],s=38,marker='D',fc='white',ec=ink,zorder=5)
    annotate(a,.575,.50,'固定对准点',8.1,ha='center')
    annotate(a,.63,.87,'队友在途参考线段',8.1,color=mid)
    A=np.array([.51,.87]); B=np.array([.875,.43]); P=np.array([.61,.60])
    Q=A+np.dot(P-A,B-A)/np.dot(B-A,B-A)*(B-A)
    a.plot([P[0],Q[0]],[P[1],Q[1]],':',c=ink,lw=1.05)
    annotate(a,.69,.70,'历史最近约 0.497 m',8.0)
    a.plot([.025,.96],[.21,.21],c=grid,lw=.7)
    annotate(a,.035,.12,'d ≥ 0.65 m   使用固定对准点',8.5)
    annotate(a,.47,.12,'d < 0.65 m   退回两点式入口',8.5)
    annotate(a,.035,.02,'回退后仍需检查通道占用、预约时段和目的地。',7.7,color=mid)
    save(f,4)

def fig05():
    f,a=diagram(w=7.5,h=3.14)
    annotate(a,.025,.93,'(a) 岗位状态',10.3,weight='bold')
    tags=['提议','确认','前往','到位待命','执行','释放']
    states=['PROPOSED','CONFIRMED','MOVING','READY','ACTIVE','RELEASED']
    x=np.linspace(.025,.825,6)
    for j,(left,tag,state) in enumerate(zip(x,tags,states)):
        box(a,left,.68,.143,.17,tag,state,fill=teal_tint if j==5 else pale)
        if j<5: arrow(a,(left+.143,.765),(x[j+1],.765))
    annotate(a,.025,.60,'保留拒绝与失败记录，服务完成后凭本地回执释放岗位。',8.0,color=mid)
    a.plot([.025,.97],[.52,.52],c=grid,lw=.7)
    annotate(a,.025,.45,'(b) 历史回合中的服务事件',10.3,weight='bold')
    centers=np.linspace(.08,.92,5)
    a.plot([centers[0],centers[-1]],[.24,.24],c=mid,lw=.8)
    entries=[('90.628','跨队请求被拒绝','x'),('115.888','B3 采样','o'),
             ('116.952','B1、B2 收到报告\n报告年龄 1.064 s','D'),
             ('138.678','B3 退出观察岗位','s'),('295.932','B2 退出运输岗位','s')]
    for xc,(t,l,m) in zip(centers,entries):
        a.plot(xc,.24,marker=m,ms=5.4,ls='',color=ink,mfc='white' if m=='D' else ink)
        annotate(a,xc,.31,t+' s',8.2,ha='center',weight='bold')
        annotate(a,xc,.16,l,7.7,ha='center',va='top')
    annotate(a,.025,.02,'事件按先后等距排列。时刻为仿真时间。',7.7,color=mid)
    save(f,5)

def fig06():
    fig,(a,b)=panels()
    fig.get_layout_engine().set(rect=(0,.065,1,.935))
    chart(a,'(a) 提供支援前后的任务与车时',y='时刻或活跃工作量 / s')
    x=np.arange(3)
    q=bars(a,x-.17,[42,37,32],.32,gray='white',hatch='///',label='不支援')
    r=bars(a,x+.17,[34,37,34],.32,gray=teal,label='支援')
    a.bar_label(q,padding=2,fontsize=8)
    a.bar_label(r,padding=2,fontsize=8)
    a.set(xticks=x,xticklabels=['R1 交付','提供者返航','活跃工作量'],ylim=(0,56))
    a.legend(loc='upper right',ncol=2)
    chart(b,'(b) 两种计分规则的选择是否一致','提供者返航期限 / s','R1 期限 / s',gridaxis='none')
    b.spines[['bottom','left']].set_visible(False)
    b.tick_params(length=0)
    b.set(xlim=(-.5,5.5),ylim=(1.5,-.5),xticks=range(6),xticklabels=[32,34,35,36,37,40],yticks=[0,1],yticklabels=[34,50])
    for row in range(2):
        for col in range(6):
            change=row==1 and col in (4,5)
            b.add_patch(Rectangle((col-.47,row-.44),.94,.88,fc=rust_tint if change else teal_tint,ec='white',hatch='//' if change else ''))
            b.text(col,row,'改变' if change else '一致',ha='center',va='center',fontsize=8.3,weight='bold' if change else 'normal')
    note(fig,'仅两组在保留工作成本时拒绝支援，省略该项后接受支援。')
    save(fig,6)


def strokes(index, bounds, specs, transform):
    from scipy.ndimage import label, binary_closing
    from skimage.morphology import skeletonize
    rgb=np.asarray(Image.open(original/f'fig{index:02}.jpg').convert('RGB').crop(bounds),dtype=np.float32)
    colors=np.asarray([m[1] for m in specs],dtype=np.float32)
    distances=np.sqrt(np.sum((rgb[:,:,None]-colors)**2,axis=3))
    owner=distances.argmin(axis=2)
    out={}
    for j,(name,_,limit) in enumerate(specs):
        mask=(owner==j)&(distances[:,:,j]<limit)&(rgb.max(axis=2)-rgb.min(axis=2)>17)
        sk=skeletonize(binary_closing(mask,iterations=2))
        comps,count=label(sk,structure=np.ones((3,3)))
        pts=set(map(tuple,np.argwhere(sk & (np.bincount(comps.ravel())[comps]>=4))))
        nb={p:[q for dy in (-1,0,1) for dx in (-1,0,1) if (dy or dx) and
               (q:=(p[0]+dy,p[1]+dx)) in pts and
               (not (dy and dx) or ((p[0]+dy,p[1]) not in pts and (p[0],p[1]+dx) not in pts))] for p in sorted(pts)}
        visited=set()
        paths=[]
        for start in sorted(nb,key=lambda p:len(nb[p])==2):
            for second in nb[start]:
                if (start,second) in visited: continue
                stack=[start,second]
                visited.update([(start,second),(second,start)])
                while len(nb[stack[-1]])==2:
                    a,b=stack[-2:]
                    c=next((q for q in nb[b] if q!=a and (b,q) not in visited),None)
                    if c is None:break
                    visited.update([(b,c),(c,b)])
                    stack.append(c)
                if len(stack)>=3:
                    arr=np.asarray(stack)[::2]
                    if len(stack)%2==0:arr=np.vstack([arr,stack[-1]])
                    paths.append(transform(arr[:,1]+bounds[0],arr[:,0]+bounds[1]))
        out[name]=paths
    return out

def plot_paths(ax,data,style):
    for name,paths in data.items():
        c,ls=style[name]
        for xx,yy in paths:
            ax.plot(xx,yy,c=c,ls=ls,lw=1.26,solid_capstyle='round',dash_capstyle='round')
    return [Line2D([],[],color=style[name][0],linestyle=style[name][1],lw=1.4,label=name) for name in data]

def fig07():
    styles={'B1':(blue,'-'),'B2':('#4F9CBB','--'),'B3':('#4F72A3',(0,(5,2))),
            'R1':(rust,(0,(5,1,1,1))),'R2':(gold,'-'),'R3':(teal,'-'),
            'R4':('#744D8C','-'),'R5':('#8C4B61',(0,(2,1)))}
    scale=lambda px,py: ((px-223)/29.0,(372-py)/29.0)
    path=strokes(7,(228,262,463,434),[
        ('B1',(33,105,153),43),('B2',(61,140,150),42),
        ('R1',(151,56,69),47),('R2',(191,115,61),52),
        ('通道',(58,101,91),32)],scale)
    path.pop('通道')
    path.update(strokes(7,(395,119,644,160),[('B3',(96,86,162),55)],scale))
    path.update(strokes(7,(449,445,577,527),[('R3',(120,77,36),60)],scale))
    path.update(strokes(7,(449,670,580,758),[('R4',(143,81,118),53)],scale))
    path.update(strokes(7,(387,580,657,624),[('R5',(96,87,110),42)],scale))
    fig,(a,b)=plt.subplots(1,2,figsize=(7.3,4.45),gridspec_kw={'width_ratios':[.95,1.25]},layout='constrained')
    fig.get_layout_engine().set(rect=(0,.07,1,1))
    def field(ax):
        ax.add_patch(Rectangle((1.9,-.51),3.2,1.02,fc=blue_tint,ec=blue,lw=.64,zorder=1))
    for ax in (a,b): field(ax)
    plot_paths(a,path,styles)
    chart(a,'(a) 八个实体的运动范围','x / m','y / m','both')
    a.set(xlim=(-.5,15.3),ylim=(-14.2,9.3),xticks=range(0,16,3),yticks=range(-14,10,4),aspect='equal')
    for xx,yy,lab in [(6.5,8.36,'B3 航点飞行'),(8.05,-8.65,'R5 航点飞行'),
                      (9,-3.9,'R3'),(9.15,-12.3,'R4')]:
        a.text(xx,yy,lab,fontsize=7.5)
    h=plot_paths(b,{name:path[name] for name in ('B1','B2','R1','R2')},styles)
    chart(b,'(b) 共享通道附近的运输轨迹','x / m','y / m','both')
    b.set(xlim=(0,8.45),ylim=(-2.5,4.3),aspect='equal',xticks=range(0,9,2),yticks=range(-2,5,2))
    b.legend(handles=h,loc='upper left',ncol=2)
    note(fig,'轨迹按原图描迹。六辆地面车由电机驱动，两架无人机按航点运动。')
    save(fig,7)

def fig08():
    fig,ax=plt.subplots(figsize=(7.1,2.72),layout='constrained')
    chart(ax,x='仿真时刻 / s',gridaxis='x')
    occ=[(13.088,25.312,3),(50.912,61.760,3),(86.416,96.944,2),
        (214.528,230.256,1),(286.320,298.880,0)]
    for start,end,y in occ:
        ax.barh(y,end-start,left=start,height=.36,color=rust if y in (3,1) else blue_tint,hatch=None if y in (3,1) else '////',edgecolor=ink,lw=.8)
    ax.scatter([240.928],[-.65],marker='D',s=24,facecolor='white',edgecolor=ink,zorder=4)
    ax.annotate('B2 因有效观察放行 · 240.928 s',(240.928,-.65),(12,0),textcoords='offset points',va='center',fontsize=8.4)
    ax.set(xlim=(0,400),ylim=(-1.1,3.64),yticks=[3,2,1,0],yticklabels=['R2','B1','R1','B2'],xticks=np.arange(0,401,50))
    ax.legend(handles=[Patch(fc=rust,ec=ink,label='红方占用'),Patch(fc=blue_tint,ec=ink,hatch='///',label='蓝方占用')],
        loc='upper right',ncol=2)
    save(fig,8)

def fig09():
    data=[
        ('红方巡察',3.480,10),('R3 侦察',8.322,60),('R4 侦察',8.520,60),('R3 报告',26.294,70),
        ('R4 报告',26.634,70),('红方巡逻',30.354,60),('蓝方巡察',32.216,40),('红方第二批交付',43.414,100),
        ('R3 返场',62.248,86),('R4 返场',118.352,130),('红方无人机返场',163.966,180),
        ('红方第一批交付',186.894,250),('蓝方第一批交付',243.432,350),('蓝方第二批交付',295.878,350)]
    fig, ax=plt.subplots(figsize=(7.05,4.72),layout='constrained')
    chart(ax,x='仿真时刻 / s',gridaxis='x')
    for i,(l,c,d) in enumerate(data):
        ax.hlines(i,c,d,colors='#AEC1CD',lw=.84)
        ax.plot(c,i,'o',ms=4.3,color=blue)
        ax.plot(d,i,'D',ms=4.3,mec=rust,mfc='white')
        ax.annotate(f'{c:.3f} / {d}',(d,i),xytext=(5,0),textcoords='offset points',ha='left',va='center',fontsize=7.6)
    ax.set(xlim=(0,423),xticks=range(0,401,50),ylim=(13.65,-.8),yticks=range(14),yticklabels=[q[0] for q in data])
    ax.legend(handles=[Line2D([],[],ls='',marker=m,mec=blue if m=='o' else rust,mfc=f,label=l)
        for m,f,l in [('o',blue,'完成时刻'),('D','white','期限')]],loc='upper right',ncol=2)
    save(fig,9)

def fig10():
    pic=Image.open(original/'fig10.jpg').convert('RGB').crop((296,91,1010,804))
    fig,ax=plt.subplots(figsize=(4.6,4.53))
    fig.subplots_adjust(left=.016,right=.984,top=.988,bottom=.012)
    ax.imshow(pic,interpolation='nearest')
    ax.axis('off')
    # The crop removes margins only. Keep the complete perimeter and original objects.
    save(fig,10)

def fig11():
    styles={'B1':(blue,'-'),'B2':('#4F9CBB','--'),'R1':(rust,(0,(5,1,1,1))),'R2':(gold,':'),'R3':(teal,'-'),'R4':('#744D8C','-')}
    center=lambda px,py:((px-586)/113.95,(595-py)/113.75)
    top=lambda px,py:(8+(px-2050)/131.25,-3+(181-py)/130.9)
    bottom=lambda px,py:(8+(px-2050)/131.25,-13+(1153-py)/130.9)
    path=strokes(11,(480,376,1520,1025),[
        ('B1',(42,103,132),53),('B2',(42,130,117),52),
        ('R1',(171,113,63),51),('R2',(127,104,154),54)],center)
    r3=strokes(11,(2030,148,2591,470),[('R3',(165,88,110),86)],top)
    r4=strokes(11,(2028,867,2600,1175),[('R4',(116,142,77),88)],bottom)
    fig=plt.figure(figsize=(7.45,3.95),layout='constrained')
    fig.get_layout_engine().set(rect=(0,.06,1,1))
    g=fig.add_gridspec(2,2,width_ratios=[1.75,1])
    a,b,c=fig.add_subplot(g[:,0]),fig.add_subplot(g[0,1]),fig.add_subplot(g[1,1])
    h=plot_paths(a,path,styles)
    plot_paths(b,r3,styles); plot_paths(c,r4,styles)
    for x,y,w,h0 in [(2.35,.50,2.3,.15),(2.35,-.65,2.3,.15),(6.91,-1.20,.19,2.4)]:
        a.add_patch(Rectangle((x,y),w,h0,fc='.83',ec='none'))
    chart(a,'(a) 中央运输区域','x / m','y / m','both')
    chart(b,'(b) 北侧侦察 · R3',y='y / m',gridaxis='both')
    chart(c,'(c) 南侧侦察 · R4','x / m','y / m','both')
    a.set(xlim=(-1.3,8.32),ylim=(-4.0,2.6),xticks=[0,2,4,6,8],yticks=[-4,-2,0,2],aspect='equal')
    b.set(xlim=(7.6,12.4),ylim=(-5.3,-2.5),xticks=[8,10,12],yticks=[-5,-4,-3])
    c.set(xlim=(7.6,12.4),ylim=(-13.4,-10.5),xticks=[8,10,12],yticks=[-13,-12,-11])
    a.legend(handles=h,ncol=4,loc='upper left')
    positions=[(a,[(503,751,644,593),(692,833,1498,414),(516,417,1185,705),(653,592,1185,486)],center),
               (b,[(2070,170,2050,181)],top),(c,[(2060,1147,2050,1153)],bottom)]
    for ax, pairs, fmt in positions:
        for quad in pairs:
            for i,m in enumerate(('s','o')):
                x,y=fmt(*quad[i*2:i*2+2])
                ax.scatter(x,y,marker=m,s=13,fc='white' if m=='s' else ink,ec=ink,lw=.65,zorder=5)
    note(fig,'方形为起点，圆形为终点。轨迹按历史原图描迹。')
    save(fig,11)

def fig12():
    events=[('R2  东 → 西',0,24.130,23.870),('B1  西 → 东',50.008,77.508,20.492),('R1  东 → 西',122.376,149.558,20.818),
        ('B1  东 → 西',184.788,209.094,23.694),('B2  东 → 西',241.330,264.256,25.074)]
    fig,ax=plt.subplots(figsize=(7.25,3.15),layout='constrained')
    chart(ax,x='仿真时刻 / s',gridaxis='x')
    for j,(l,start,end,saved) in enumerate(events):
        ax.barh(j,end-start,left=start,height=.31,color=teal,edgecolor=ink,lw=.65)
        ax.barh(j,saved,left=end,height=.31,color=teal_tint,edgecolor=ink,lw=.65,hatch='////')
        ax.text(start,j-.25,f'{start:.3f}–{end:.3f}',ha='left',va='bottom',fontsize=7.6)
        ax.text(end+saved+4,j,f'提前 {saved:.3f} s',ha='left',va='center',fontsize=7.5,color=mid)
    ax.set(xlim=(0,338),ylim=(4.55,-.95),yticks=range(5),yticklabels=[q[0] for q in events],xticks=range(0,301,50))
    ax.legend(handles=[Patch(fc=teal,ec=ink,label='实际持有'),Patch(fc=teal_tint,ec=ink,hatch='////',label='名义窗内提前释放')],
        loc='upper right',ncol=2)
    save(fig,12)


def fig13():
    fig,ax=plt.subplots(figsize=(6.9,3.21),layout='constrained')
    chart(ax,y='交付时刻 / s')
    x=np.arange(3)
    q=bars(ax,x-.16,[187.784,245.572,298.556],.29,gray='white',hatch='///',label='联合机制关闭')
    r=bars(ax,x+.16,[183.448,239.198,295.480],.29,gray=teal,label='联合机制开启')
    ax.bar_label(q,fmt='%.3f',padding=3,fontsize=8.0)
    ax.bar_label(r,fmt='%.3f',padding=3,fontsize=8.0)
    for xi,v,delta in zip(x,[187.784,245.572,298.556],[4.336,6.374,3.076]):
        ax.text(xi,v+29,f'提前 {delta:.3f} s',ha='center',fontsize=8.4,weight='bold')
    ax.set(ylim=(0,360),xticks=x,xticklabels=['红方第一批交付','蓝方第一批交付','蓝方第二批交付'])
    ax.legend(loc='upper left')
    save(fig,13)

def fig14():
    fig,(a,b)=panels()
    fig.get_layout_engine().set(rect=(0,.06,1,1))
    x=np.arange(4)
    y=[.0166,.0397,.0164,.0183]
    a_values=[.01,.03,.01,.01]
    d=[.123,.856,.871,.845]
    labels=['标称','提高噪声','宽柱','窄柱']
    chart(a,'(a) 扫描估计与噪声设定','', '噪声标准差 / m')
    chart(b,'(b) 实际轨迹到柱心的距离','', '最小距离 / m')
    qa=bars(a,x,y,.55,blue)
    qb=bars(b,x,d,.55,teal)
    a.bar_label(qa,fmt='%.4f',padding=3,fontsize=7.8)
    b.bar_label(qb,fmt='%.3f',padding=3,fontsize=7.8)
    m=a.scatter(x,a_values,marker='D',fc='white',ec=ink,s=24,label='设定值',zorder=4)
    a.legend(handles=[m,Patch(fc=blue,ec=ink,label='估计中位数')],loc='upper left')
    a.yaxis.set_major_formatter(FormatStrFormatter('%.02f'))
    a.set(xticks=x,xticklabels=labels,ylim=(0,.052))
    b.set(xticks=x,xticklabels=labels,ylim=(0,1.03))
    note(fig,'每种条件对应一个历史回合；柱心距离以车体参考点计算。')
    save(fig,14)

def fig15():
    fig=plt.figure(figsize=(7.45,4.05),layout='constrained')
    g=fig.add_gridspec(2,2,width_ratios=[.98,1.15],hspace=.035)
    a=fig.add_subplot(g[0,0]); b=fig.add_subplot(g[1,0],sharex=a); c=fig.add_subplot(g[:,1])
    chart(a,'(a) 固定阈值的五档对照',y='报价 / 条')
    xs=np.arange(5)
    bars(a,xs,[2.67]*4+[0],.61,blue)
    a.set(ylim=(0,3.26),yticks=[0,1,2,3])
    a.tick_params(axis='x',labelbottom=False)
    chart(b,'',y='红方按期率')
    b.plot(xs,[1.0]*4+[.8788],color=rust,marker='o',lw=1.35,ms=3.9)
    b.annotate('0.8788',(4,.8788),xytext=(-7,-1),textcoords='offset points',ha='right',fontsize=7.4)
    b.set(ylim=(.81,1.03),yticks=[.85,.90,.95,1.0],xticks=xs,
          xticklabels=['.05/.05','.30/.70','.50/.50','.70/.70','.90/.90'],xlabel='阈值对  R3 / R4')
    b.tick_params(axis='x',labelsize=7)
    chart(c,'(b) 三个场景中的阈值变化','试验回合','响应阈值 θ')
    n=np.arange(1,7)
    c.plot(n,[.55]*6,c=teal,marker='o',ms=4.2,lw=1.08,label='受扰动 R3、R3 放宽 R4、自有预算 R3')
    c.plot(n,[.25,.05,.05,.05,.05,.05],c=blue,marker='s',ms=4,lw=1.12,label='受扰动 R4')
    c.plot(n,[.40,.25,.10,.05,.05,.05],c=rust,ls='--',marker='D',mfc='white',ms=4.8,lw=1.25,label='R3 放宽 R3、自有预算 R4')
    c.set(ylim=(0,.88),xticks=n,yticks=np.arange(0,.81,.2))
    c.legend(loc='upper left',fontsize=7.2)
    c.annotate('重合曲线合并标示',(2,.55),xytext=(0,-13),textcoords='offset points',ha='center',fontsize=7.5,color=mid)
    save(fig,15)

def fig16():
    fig,(a,b)=panels()
    fig.get_layout_engine().set(rect=(0,.075,1,1))
    chart(a,'(a) 蓝方按期任务与通道争用','实体数 N','蓝方按期任务数')
    n=np.arange(6,11)
    a.plot(n,[3]*5,c=teal,marker='o',mfc='white',ms=5.5,lw=1.25,label='新增实体停在整备节点')
    a.plot(n,[3,3,2,1,1],c=rust,marker='s',ms=3.45,lw=1.25,ls='--',label='新增实体同争一条通道')
    for i,y in zip(n,[3,3,2,1,1]):
        if y<3:a.text(i,y-.22,f'{y}/3',ha='center',fontsize=7.6)
    a.text(6.01,3.55,'争用条件的时隙交易事件：9 → 0 → 0 → 0 → 0',fontsize=7.3,color=mid)
    a.set(xlim=(5.77,10.25),ylim=(0,3.83),xticks=n,yticks=range(4))
    a.legend(loc='lower left',fontsize=7.4)
    chart(b,'(b) 预约数量与单次决策耗时','已登记预约 / 条','单次决策中位耗时 / ms')
    x=np.array([1,5,9,17,25,33,49])
    # Interior observations are read from the source plot, calibrated against grid ticks.
    y=1.0+(919-np.array([905,964,776,640,482,578,159]))/1642
    y[0]=1.0085
    y[-1]=1.4631
    b.plot(x,y,c=blue,marker='o',ms=4.7,lw=1.15,label='中位耗时')
    b.plot(x,.9818+.00937*x,c=rust,ls='--',lw=1.25,label='原报告的线性拟合')
    b.set(xlim=(0,51),ylim=(.927,1.52),xticks=np.arange(0,51,10))
    b.legend(loc='upper left',fontsize=7.5)
    b.text(49,.973,'斜率 0.00937 ms/条，截距 0.9818 ms\n$R^2=0.9129$',ha='right',va='bottom',fontsize=7.5,color=mid)
    note(fig,'耗时曲线的端点和拟合系数沿用原文，中间五点按原图读数。')
    save(fig,16)

if __name__=='__main__':
    import sys
    values=[int(arg) for arg in sys.argv[1:]] or list(range(1,17))
    for i in values:
        globals()[f'fig{i:02}']()
        print(f'Figure {i:02}',flush=True)
