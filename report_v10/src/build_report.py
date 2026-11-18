# -*- coding: utf-8 -*-
"""Build v10 course report from amax Webots evidence (DOCX + PDF)."""
import json, os, glob, math
import subprocess, os, json, glob
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

REPO='/home/liujingzhi/pandaoxi/gongyu-ros2-gazebo'
OUT=os.path.join(REPO,'report_v10')
FIG=os.path.join(OUT,'figures')
os.makedirs(FIG,exist_ok=True)
EV=os.path.join(REPO,'evidence','webots')
RUNROOT='/home/liujingzhi/pandaoxi/gongyu-webots-runs'


def summary(tag):
    path=tag if tag.endswith('summary.json') else os.path.join(EV,tag,'summary.json')
    return json.load(open(path,encoding='utf-8'))
def metrics(tag):
    return json.load(open(os.path.join(EV,tag,'metrics.json'),encoding='utf-8'))
def events(tag):
    return [json.loads(l) for l in open(os.path.join(EV,tag,'events.jsonl'),encoding='utf-8')]

S={os.path.basename(os.path.dirname(p)):summary(p) for p in glob.glob(EV+'/*/summary.json')}
gps=S['b-loc-gps-01']['analysis']['own_estimate_rmse_m']
odom=S['b-loc-odom-01']['analysis']['wheel_odom_rmse_m']

subprocess.run(['/home/liujingzhi/miniconda3/bin/python','/tmp/draw_figs.py'],check=True)

# ---------------- DOCX ----------------
doc=Document()
sec=doc.sections[0]
sec.top_margin=Cm(2.4);sec.bottom_margin=Cm(2.2);sec.left_margin=Cm(2.7);sec.right_margin=Cm(2.5)
normal=doc.styles['Normal'];normal.font.name='Times New Roman';normal.font.size=Pt(10.5)
_rp=normal._element.get_or_add_rPr()
_rf=_rp.find(qn('w:rFonts'))
if _rf is None:
    _rf=OxmlElement('w:rFonts');_rp.insert(0,_rf)
_rf.set(qn('w:eastAsia'),'宋体')
def para(text,size=10.5,bold=False,align=None,space=6,font='宋体'):
    p=doc.add_paragraph();r=p.add_run(text);r.font.size=Pt(size);r.bold=bold
    r.font.name='Times New Roman';r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),font)
    p.paragraph_format.space_after=Pt(space)
    if align is not None:p.alignment=align
    return p
def head(text,level=1):
    p=doc.add_heading(level=level);r=p.add_run(text);r.font.name='Times New Roman'
    r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'黑体')
    r.font.size=Pt(15 if level==1 else 12.5);r.font.color.rgb=RGBColor(0x1F,0x38,0x64)
    return p
def table(rows,widths=None):
    t=doc.add_table(rows=0,cols=len(rows[0]));t.style='Light Grid Accent 1';t.alignment=WD_TABLE_ALIGNMENT.CENTER
    for i,row in enumerate(rows):
        cells=t.add_row().cells
        for j,v in enumerate(row):
            cells[j].text='';p=cells[j].paragraphs[0];r=p.add_run(str(v));r.font.size=Pt(8.8)
            r.font.name='Times New Roman';r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'宋体')
            if i==0:r.bold=True
    return t
def pic(path,width=15.5):
    doc.add_picture(path,width=Cm(width));doc.paragraphs[-1].alignment=WD_ALIGN_PARAGRAPH.CENTER

para('无人系统导论课程设计报告 · 题目二',20,True,WD_ALIGN_PARAGRAPH.CENTER,10,'黑体')
para('空地协同靶场：从课件原理到 Webots 整机实跑',15,True,WD_ALIGN_PARAGRAPH.CENTER,14,'黑体')
para('潘道熙　25361130　　版本 v10-course　　2026-11-19',10.5,False,WD_ALIGN_PARAGRAPH.CENTER,18)
head('摘要',1)
para('本报告以《无人系统导论》题目二为任务来源，围绕共享通道资源竞争、时效观测与六车两机协同交付，'
 '说明我们从课件学到了什么、如何据此选择方案，以及哪些实跑证据支持这些选择。整体路线以 v9-course 为复现与对照基线，'
 '在独立开发区完成需求分解、Webots 世界与控制器开发，并在 amax 服务器上完成阶段 B/C/D/E/F 的受控实验。'
 '正式验收回合 f-webots-full-01 为 6 辆 UGV 加 2 架 UAV 的完整 Webots 回合：14 项任务全部按期、0 条定义碰撞、'
 '0 条逻辑违例、5 次通道持有与释放，关闭回执状态 COMPLETE。对照回合保留了全关机制下的 2 条通道重叠违例、'
 '报告过期未触发服务、低矮障碍下双扫描命中差异等负结果。报告同时明确写出当前后端的能力边界：'
 '正式整机证据使用独立裁判的运动学真值，真实电机模式仅完成单机定位并定位了整机停滞的原因，未作为电机驱动整机交付。')
para('关键词：多无人系统协同；Webots；共享通道；机会成本；时效观测；同源证据',10.5,True,space=12)

head('1　课程问题如何变成设计问题',1)
para('题目二要求设计一个智能无人系统对抗靶场，讨论仿生集群协同行为并给出至少一项行为仿真 Demo，实体数 3–10，'
 '报告不少于 3500 字。我们选择 6 UGV＋2 UAV：地面车承担运输、巡检与交付，空中平台承担观测与报告，'
 '两类实体通过同一任务语义协同；场地中设置一条窄通道，使“通行权”成为可观测、可争用、可评价的资源。'
 '下面五个问题贯穿正文，每一个都从原课件的具体页面推出，而不是从工具清单倒推。')
table([
 ['编号','课件依据（讲次·题号·slide）','课程原理','落到本项目的设计问题'],
 ['Q1','第一讲第5题 slide81–96；第二讲第3题 slide39–40','用户需求→技术需求→功能逻辑分解→方案；A→B 自主运动含地形推断、机动与通信','两作业区之间只有一条窄通道，必须把“通行”拆成感知、定位、规划、控制、资源与验收'],
 ['Q2','第二讲第5、7题 slide104–121；第三讲第10题 slide129/132','多传感器冗余覆盖；LiDAR、GNSS/IMU 与地图加强定位；世界坐标系是规划前提','车体前后与低矮障碍各有盲区，单路扫描会漏掉两扫描平面之间的障碍'],
 ['Q3','第一讲第9题 slide118–120；第四讲 slide136、165–169','导航提供状态，制导生成航迹，控制驱动执行机构；飞控含传感器、计算机与伺服','UGV 与 UAV 共用任务语义但执行链不同，真值不得冒充 UAV 自主反馈'],
 ['Q4','第一讲第10题 slide165；第三讲第11题 slide141–145；第六讲第7题 slide101–102','任务规划按任务与载荷制定路线并分配；预规划与重规划；军蚁活桥是仿生参考','B3 观测过期后仍按旧信息派岗位会让地面车白等，帮助他人存在机会成本'],
 ['Q5','第二讲 slide209–210；第一讲第4题 slide68','技术性能、战术效能、操作效用分层；集群智能是思想来源而非实现证明','“实际清空后提前释放”必须在交付是否按期、下游是否等待的层面评价'],
])
para('口径修正沿用逐页核对结果：第三讲第 6 题是地面效应，任务规划是第 11 题；slide156–158 的 0–10 级是 UAV GNC 能力描述，'
 '不等于整套系统的自主等级；0.65 m 是旧版入口对准检查阈值而非通道净宽，0.5 m/s 是任务图估算速度而非轮速命令上限。'
 '正文不再沿用旧清单中的等级、阈值与题号。',space=12)

head('2　最终设计与可复现架构',1)
para('系统由三层组成。任务逻辑层维护冻结场景卡（14 项任务及期限）、角色路线、报告有效期 τ、预约与释放规则；'
 'Webots 后端层包含参数化世界、八实体控制器与独立裁判；验收层保存原始事件、指标、关闭回执与场景哈希。'
 '世界由 webots/tools/generate_world.py 按冻结场景卡生成，控制器通过消息总线接收目标点并回报传感器遥测，'
 '裁判独立记录真值、任务完成时刻、通道占用区间与资源时序。这样正文中的每个数字都能定位到平台、版本、场景和回合。')
para('为排除“只改场景不改规则”的混淆，所有受控实验固定场景几何、任务卡、控制周期、消息延迟与随机种子，'
 '只改变矩阵中列出的唯一变化因素。跨平台只比较行为能否复现，不把 Webots 仿真秒数与 Gazebo 墙钟或历史回合混算。')
table([
 ['实验','场景','A 处理','B 处理','唯一变化因素','证据回合'],
 ['B-loc','web_b1_route','轮式里程计','GPS 闭环','定位来源','b-loc-odom-01..03 / b-loc-gps-01..03'],
 ['B-scan','web_b1_open','仅主雷达','主雷达＋低位扫描','低矮障碍是否存在','b-scan-open / b-scan-lowobs 各 3 回合'],
 ['C-ref / C-auto','web_b3_target','参考反馈标签','传感器反馈标签','反馈来源声明','c-ref-01..03 / c-auto-01..03'],
 ['D-report','web_medium','按时到达','有效期后到达','报告到达延迟','d-report-ontime / d-report-expired'],
 ['D-adapt / D-cost','web_medium','原回退 / 低成本','动态改派 / 高机会成本','策略或机会成本','d-adapt / d-cost-high'],
 ['E-mech','web_medium','phase111 全关','release 实际清空释放','释放机制开关','e-mech-phase111 / e-mech-release'],
 ['F-holdout / F-full','web_holdout_v1 / web_medium','—','最终方案','预登记留出 / 正常运行','f-holdout-v1 / f-webots-full-01'],
])
para('复现入口为 webots/tools/run_webots.sh <scene> <run-id>；默认运动学裁判后端，'
 'GONGYU_PHYS=1 切真实电机实验，GONGYU_NO_RENDER=1 关闭主视图渲染。每次运行的新运行 ID、'
 '场景 SHA256、原始事件、指标与关闭回执写入独立目录，摘要提交到仓库 evidence/webots/<run-id>/。',space=12)

head('3　地面车：双扫描、定位与通行',1)
para('B-scan 使用同一条单车路线，仅在布局层放入位于两扫描平面之间的低矮障碍。低位扫描在障碍布局中出现 2 次有效命中，'
 '开阔布局为 0 次；原始 lidar_low_front 序列与到位事件保存在对应回合，说明环境变化确实进入了控制器输入，'
 '而不是事后补写的标签。图4给出对照。')
pic(os.path.join(FIG,'scan.png'),13.2)
para('B-loc 在同一轨迹上比较两种定位来源。GPS 闭环的自身估计对独立裁判真值的位置 RMSE 为 %.3f m，'
 '轮式里程计为 %.3f m；后者在转弯与滑移段积累了明显偏差。这里把“回放计算”和“实际闭环”分开登记：'
 '裁判真值来自独立状态机，控制器估计来自其声明的传感器输入，二者不共用同一条写入路径。'%(gps,odom))
pic(os.path.join(FIG,'loc_rmse.png'),13.2)
para('通行规则不是“预约到点就放行”。裁判按真实位置重建进入、清空与释放时间线；phase111 作为全关对照出现 2 条通道重叠违例，'
 'release 在同一源码版本、同一场景下为 0 条。这个配对说明改变的是规程本身，而不是车辆速度或场景几何。',space=12)

head('4　空中观测与空地协同',1)
para('UAV 侧先建立参考回合，再建立声明传感器反馈的回合。c-ref 与 c-auto 的事件流中 feedback_mode 分别为 reference 与 sensor，'
 '传感位姿对裁判真值的 XY RMSE 为 0.114 m；观测载荷通过机载相机生成带时间戳的报告签名，裁判不直接把目标标签交给控制器。'
 '必须说明的是：当前运动学后端中该开关只改变反馈来源标签，并不改变运动学，因此这两组回合证明的是来源可追溯与报告可生成，'
 '不能单独用来宣称自主飞行效能。真正的电机闭环仍是第 7 节列出的边界。')
para('报告时效实验把同一次采样的内容保持不变，只改变到达延迟。d-report-ontime 中 9 份报告在有效期内到达并被采用；'
 'd-report-expired 中 9 份过期报告均未触发依赖有效信息的服务；d-adapt 对同样的过期条件给出 9 次动态补采/改派决策，'
 '候选与拒绝理由写入事件。d-cost-high 单独改变机会成本，保留“成本过高时不改派”的负结果。'
 '这条链路从传感器观测、报告生成、到达判定、角色选择一直到执行事件，均可在同一回合内追到。',space=12)

head('5　共享通道与系统效能',1)
para('通道实验用独立裁判重建资源时间线。e-mech-phase111 保留 2 条重叠违例作为全关基线；e-mech-release 在同样任务与几何下'
 '提前释放且 0 违例；f-holdout-v1 在预登记留出布局中仍为 14/14 按期、0 违例。'
 '我们没有用一次放行的压缩余量代替全队交付结果：局部收益是否传到下游，要看任务完成时刻与下游等待事件是否同时改善。')
pic(os.path.join(FIG,'channel.png'),15.0)
para('按课程三层度量收口：技术性能层看位置误差、低位扫描命中与通道净距；任务效能层看按期数、报告采用/过期与下游等待；'
 '系统效用层看规定场景内的 14/14 完成率、0 逻辑违例和留出布局下的退化行为。三层的适用范围不同，不能互相替代。',space=12)

head('6　Webots 整机算例',1)
para('正式场景按课堂“建模—编程—仿真”顺序搭建：世界中可打开查看六车两机、泊位、通道、作业区与地标，'
 '控制器按声明的传感器输入执行任务，裁判独立核验。f-webots-full-01 的完整窗口内 14 项任务全部按期，'
 '通道 5 次持有与 5 次清空，0 条违例，关闭回执 COMPLETE，墙钟 %.1f s。'%S['f-webots-full-01']['wall_seconds'])
pic(os.path.join(FIG,'trajectory.png'),15.5)
para('为了便于课堂演示，仓库 docs/demo/webots_replay.html 提供自包含的深色科技风同源回放：'
 '播放/暂停、四档速度、时间轴拖拽，以及开始、协同报告、共享通道、交付四个章节跳转。'
 '页面中的轨迹来自主回合原始遥测抽样，事件来自同一回合事件流，数字取自 metrics.json；'
 '节点间线性插值只用于视觉连续，不作为新的测量值。',space=12)

head('7　局限、负结果与验收边界',1)
para('第一，正式整机证据采用独立裁判的运动学真值模型，裁判维护每个实体的目标点与通道门控，并写回仿真位姿；'
 '这一设计保证时间线可复算，但不能等同于电机驱动的真实运动。为此我们实现了 GONGYU_PHYS=1 真实电机分支：'
 'UGV 四轮与 UAV 四桨由控制器 setVelocity 驱动，裁判只读 getPosition()。诊断中发现静态地面被误设为动态物理体，'
 '导致整车自由落体；修正为静态地面后，单机可完成入口与到位并保留 IMU 航向、限幅轮速。'
 '但 8 实体整机在约 29 s 处停于 L→O 路段，未形成完整 14/14，故该分支只作为实验记录，不进入最终验收结论。')
para('第二，矩阵中 web_b1_gate、web_b1_unmapped、web_long、web_cost 等专门世界尚未生成；'
 'B 阶段的 Dijkstra/A* 与出口泊位检查仍由 v9 Gazebo 证据支撑，报告中明确标注平台与回合，不与 Webots 数据合并统计。')
para('第三，受控处理的三次重启使用种子 0/1/2，但冻结模型不含随机扰动，结果确定性一致；'
 '因此按“独立重启”登记样本量，不宣称统计方差或置信区间。')
para('第四，留出布局在规则冻结后运行，未用留出结果回头调参；若未来改变车辆动力学或传感器模型，'
 '本报告的时间余量结论需要重新验证。以上是当前证据能支持的范围，超出部分不写成已完成。',space=12)

head('　补充说明：方法选择的推理链',1)
para('之所以把“共享通道”作为全项目的主要矛盾，而不是把它当成普通路径规划里的一个障碍物，是因为课件在总体设计流程中先要求把用户需求转成技术需求，再按功能逻辑分解。题目给出的场景只有两个作业区，实体数限定在 3–10，若各车各自求最短路，窄通道必然成为多个任务同时争用的同一份资源；此时“谁先过”决定的不是某辆车的局部耗时，而是其他车的期限余量和下游泊位是否被占。于是我们把功能拆成感知、定位、规划与控制、资源规程、报告与验收六块，并为每一块指定可观测输出：扫描命中与原始距离、自身估计相对独立真值的误差、到位与驻留事件、通道进入/清空/释放时间线、报告采样与到达时刻、任务完成与违例计数。这个分解直接来自第一讲第 5 题所讲的“需求→技术需求→功能逻辑分解→方案”，也回应了第二讲关于通信接口与可靠性的要求。')
para('在感知方案上，我们没有因为 LiDAR 量程大而直接选单路扫描，而是先把车体前方、侧向与低位三个方向的遮挡关系写成可检验问题：是否存在位于两扫描平面之间、基础地图中没有、且原路径确实经过的障碍。B-scan 用同一条路线与同一套控制器，只在布局层改变这个障碍的存在性，低位扫描命中从 0 变为 2，且原始距离序列保留在回合目录中。这才使“双扫描优于单路”成为有条件的结论：只在我们验证过的障碍高度、量程与采样频率范围内成立。定位方案同理，轮式里程计在转弯与滑移时会漂移，而 GPS 闭环把误差压到 0.074 m；我们没有把回放误差冒充闭环结果，而是分别记录控制器实际读取的输入与裁判保存的真值。')
para('在协同方案上，军蚁活桥给我们的启发是“帮助他人有代价”，而不是把仿生名词贴到系统图上。我们把代价具体化为机会成本：提供帮忙的车要推迟自己的本职任务，请求方能否因此按期，取决于剩余期限、替代岗位是否空闲以及报告是否仍在有效期。d-cost-high 保留了“算下来不划算就不改派”的负结果，d-adapt 则给出触发、候选与决策事件；两者放在一起才能说明规则何时有效。同理，通道释放不只看入口何时放行，还要看出口与交付区是否真的清空，否则局部收益会在下游被等待抵消。第三讲任务规划与第二讲三层度量的课程原理，在这里被落成了可复算的事件，而不是一句“我们实现了协同”。')
para('关于平台选择，课件把建模、编程与仿真列为 Webots 使用的三个环节，我们在 Webots 中完成世界搭建、原生 Python 控制器与整机仿真，使老师可以直接打开世界查看八实体与通道，也可以按说明复跑一个回合。Gazebo 继续承担筛选和历史对照，但我们在表格里始终标注平台与版本，不把两个后端的秒数或完成率相加。这样做的代价是 Webots 运动学后端在电机层面并不完整；我们没有把这个缺口藏进“仿真假设”四个字，而是单列真实电机分支的负结果、已修的静态地面与航向漂移问题，以及整机仍未闭合的事实。报告宁可把边界写清楚，也不把未验证的能力写成结论。')
head('8　结论',1)
para('本轮把题目二的课程原理落实为可运行的空地协同靶场，并用同源实跑证据支撑关键取舍：'
 '双扫描补到了低矮障碍，GPS 闭环显著优于纯轮式里程计，过期报告不能触发服务且动态改派有可追的候选理由，'
 '实际清空后释放优于全关规程，最终方案在见过场景与预登记留出场景均达到 14/14、0 违例。'
 '我们同时保留了负结果与真实电机整机的未闭合边界，使老师能沿着正文看到“课件原理—设计问题—方案—验证证据”的完整链条，'
 '而不是只看到一组汇总数字。')

head('附录 A　证据索引',1)
rows=[['回合','场景','按期','违例','关键用途']]
for tag in ['b-scan-open-01','b-scan-lowobs-01','b-loc-gps-01','b-loc-odom-01','c-ref-01','c-auto-01',
            'd-report-ontime','d-report-expired','d-adapt','d-cost-high','e-mech-phase111','e-mech-release',
            'f-holdout-v1','f-webots-full-01']:
    x=S[tag]
    rows.append([tag,x['scene'],f"{x['on_time']}/{x['total']}",x['violations'],x['variant'] if 'variant' in x else tag.split('-')[0]])
table(rows)
para('全部 26 个回合的 metrics / events / shutdown / summary / scene.sha256 位于仓库 evidence/webots/<run-id>/；'
 '原始日志位于 amax ~/pandaoxi/gongyu-webots-runs/<run-id>/。',space=12)

head('附录 B　复现与核验清单',1)
para('1）在 amax 上拉取仓库并核对场景哈希；2）按 docs/course_alignment/实验矩阵.md 选定场景与唯一变化因素；'
 '3）用新运行 ID 调用 webots/tools/run_webots.sh，检查 webots_exit=0 与 shutdown.json 的 COMPLETE；'
 '4）从 metrics.json 复算按期数、报告采用/过期数、通道进入/释放数与违例数；'
 '5）打开 docs/demo/webots_replay.html 核对同源演示；6）对照 docs/acceptance_status.md 查看尚未闭合的边界。')

docx_path=os.path.join(OUT,'潘道熙25361130课程设计报告题目二_v10.docx')
doc.save(docx_path)
print('DOCX',docx_path,os.path.getsize(docx_path))
