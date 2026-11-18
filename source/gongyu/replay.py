"""Render actual graph event traces into standalone offline replay and report plots."""
import argparse
import csv
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path


def render(run_dir):
    run_dir = Path(run_dir)
    card = json.loads((run_dir/'scenario.json').read_text())
    manifest = json.loads((run_dir/'manifest.json').read_text())
    events = [json.loads(x) for x in (run_dir/'events.jsonl').read_text().splitlines()]
    with (run_dir/'trajectory.csv').open() as f:
        rows = [{**r,'t_ms':int(r['t_ms']),'x':float(r['x']),'y':float(r['y'])} for r in csv.DictReader(f)]
    decisions=[json.loads(x) for x in (run_dir/'decisions.jsonl').read_text().splitlines()]
    diagnostics_path=run_dir/'diagnostics.jsonl'
    diagnostics=[json.loads(x) for x in diagnostics_path.read_text().splitlines()] if diagnostics_path.exists() else []
    data = {'card':card,'manifest':manifest,'events':events,'trajectory':rows,'decisions':decisions,'diagnostics':diagnostics}
    html = TEMPLATE.replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/'))
    (run_dir/'replay.html').write_text(html,encoding='utf-8')
    plot_age(run_dir,events,card)
    if 'geometry' in card:
        plot_geometry(run_dir,card)
    provenance={'run_id':manifest['run_id'],'runtime_revision':manifest['code_revision'],
                'renderer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'generated_at':datetime.now(timezone.utc).isoformat(),
                'artifact_sha256':{name:hashlib.sha256((run_dir/name).read_bytes()).hexdigest()
                    for name in ('replay.html','report_age_timeline.png','report_age_timeline.svg')}}
    if 'geometry' in card:
        for name in ('geometry_checks.png','geometry_checks.svg'):
            provenance['artifact_sha256'][name]=hashlib.sha256((run_dir/name).read_bytes()).hexdigest()
    (run_dir/'render_manifest.json').write_text(json.dumps(provenance,indent=2)+'\n')


def plot_geometry(out,card):
    from math import dist
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from .geometry import Geometry
    g=Geometry(card['geometry']);config=card['geometry'];target=config['device']
    fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    for ax,mode,height,names in ((axes[0],'ground',config['heights']['ground'],['L','O','J']),
                                 (axes[1],'air',config['heights']['blue_air'],['H','K','F'])):
        for box in config['obstacles']:
            lo,hi=box['minimum'],box['maximum']
            ax.add_patch(Rectangle(lo[:2],hi[0]-lo[0],hi[1]-lo[1],facecolor='#bab4a8',alpha=.7))
            ax.annotate(f"{box['id']}\nh={hi[2]:g}m",(lo[0],hi[1]),xytext=(4,7),textcoords='offset points',fontsize=8)
        for name in names:
            p=(*card['nodes'][name][:2],height);valid=g.can_observe(p,mode)
            ax.plot([p[0],target[0]],[p[1],target[1]],color='#367e57' if valid else '#ba5742',ls='-' if valid else '--')
            ax.scatter(p[0],p[1],s=60,color='#276c9c')
            reason='visible' if valid else 'out of range' if dist(p,target)>config['sensors'][mode]['range_m'] else 'occluded'
            ax.annotate(f'{name}: {reason}',p[:2],xytext=(-5 if name=='F' else 5,-16),
                ha='right' if name=='F' else 'left',textcoords='offset points',fontsize=8)
        ax.scatter(target[0],target[1],s=75,marker='*',color='#9e3558',zorder=5,label='device')
        ax.set(title=f'{mode} observation at z={height:g}m',xlabel='x (m)',ylabel='y (m)')
        ax.grid(alpha=.2);ax.margins(.25);ax.legend(loc='lower left')
    fig.suptitle('Frozen geometry checks: range + ideal aiming + 3D ray/box occlusion\nTop views; green = valid. This is a model check, not a camera or Gazebo screenshot.',fontsize=11)
    fig.savefig(out/'geometry_checks.png',dpi=180);fig.savefig(out/'geometry_checks.svg')
    plt.close(fig)


def plot_age(out,events,card):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(2,1,figsize=(10,6),gridspec_kw={'height_ratios':[1.3,1]},constrained_layout=True)
    ax,bx = axes
    loads = [e for e in events if e['kind']=='load_started']
    rejects = [e for e in events if e['kind']=='report_rejected']
    for e in loads:
        t = e['t_ms']/1000
        age = e['payload']['report_age_ms']/1000
        ax.scatter(t,age,color='#17694d',s=65,zorder=3)
        ax.annotate(e['task_id'],(t,age),xytext=(5,8),textcoords='offset points')
    for e in rejects:
        ax.scatter(e['t_ms']/1000,e['payload']['age_ms']/1000,marker='x',color='#b6422b',s=70)
    ax.axhline(card['tau_ms']/1000,color='#b6422b',ls='--',label='Freshness limit')
    ax.set(xlabel='Simulation time (s)',ylabel='Report age at sampling (s)',title=out.name+' | graph backend')
    ax.legend(loc='upper right')
    actors = list(card['fleet'])
    for e in events:
        if e['kind']=='move_started':
            i = actors.index(e['actor'])
            bx.broken_barh([(e['t_ms']/1000,e['payload']['duration_ms']/1000)],(i-.25,.5),
                           facecolors='#276c9c' if e['actor'].startswith('B') else '#bc6148')
        elif e['kind']=='delivery':
            i = actors.index(e['actor'])
            bx.scatter(e['t_ms']/1000,i,marker='*',s=90,c='black',zorder=3)
    bx.set(yticks=range(len(actors)),yticklabels=actors,xlabel='Simulation time (s)',title='Movement intervals and actual deliveries (*)')
    bx.grid(axis='x',alpha=.25)
    fig.savefig(out/'report_age_timeline.png',dpi=180)
    fig.savefig(out/'report_age_timeline.svg')
    plt.close(fig)


TEMPLATE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>共域 · 图模型证据回放</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f2f1ed;color:#20302c;font:15px "Microsoft YaHei",sans-serif}
header{padding:20px 28px;background:#173c36;color:white}h1{margin:0;font-size:26px}header p{margin:8px 0 0;color:#d3e2d9}
main{padding:20px 28px;max-width:1500px;margin:auto}.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:15px}
button,input{font:inherit}button{background:white;border:1px solid #b6c3bd;padding:9px 13px;border-radius:4px;cursor:pointer}button:hover{background:#e5ece8}
.grid{display:grid;grid-template-columns:minmax(550px,1.5fr) minmax(380px,1fr);gap:18px}.panel{background:white;border:1px solid #d3dad5;padding:16px;border-radius:5px}
canvas{width:100%;display:block}h2{font-size:18px;margin:0 0 12px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:7px;text-align:left;border-bottom:1px solid #e1e6e1}.badge{padding:5px 10px;background:#e5eee7;color:#235b41;border-radius:3px;font-weight:bold}
#timeline{max-height:210px;overflow:auto;font-size:13px;line-height:1.8}#timeline div{border-bottom:1px solid #edf0ed}footer{margin-top:14px;color:#607068;font-size:12px;line-height:1.7}.status{font-weight:bold;color:#983e29}#clock{font-size:23px;font-variant-numeric:tabular-nums}#report{font-size:14px;line-height:1.8;min-height:85px}
@media(max-width:1050px){.grid{grid-template-columns:minmax(0,1fr)}main{padding:16px}header{padding:18px}canvas{height:auto}}
</style>
<header><h1>共域｜任务依赖与交付过程</h1><p id="identity"></p></header>
<main><div class="controls"><span class="badge">实际日志回放 · 图模型</span><button id="play">播放 / 暂停</button><button data-t="0">初始状态</button><button id="reject">首次报告过期</button><button id="sample">首次合法取样</button><button id="handoff">首次交接生效</button><button id="finish">最终结果</button><input aria-label="仿真秒数" id="time" type="number" step="0.1" min="0" value="0" style="width:90px"><span id="clock"></span></div>
<div class="grid"><div class="panel"><h2>空地实体与真实位置</h2><canvas id="map" width="800" height="410"></canvas><p style="font-size:12px;color:#607068">蓝色：被测团队 B1/B2/B3　红色：任务型靶标 R1/R2/R5。虚线为空中边；坐标是图模型示意，不代表物理碰撞已验证。</p></div>
<div class="panel"><h2>取样依赖检查</h2><div id="report"></div><h2>任务与实际交付</h2><table><thead><tr><th>任务</th><th>截止</th><th>实际完成</th><th>状态</th></tr></thead><tbody id="tasks"></tbody></table></div></div>
<div class="panel" style="margin-top:16px"><h2>组织交接与已兑现的服务关系</h2><p id="decision"></p><table><thead><tr><th>实体</th><th>当前岗位</th><th>协议状态</th><th>生效时刻</th></tr></thead><tbody id="roles"></tbody></table><p id="edges"></p><p id="contractmode" style="font-size:12px;color:#607068">READY表示实际到位；报告送达且合格后，才计为取样服务可用。本轮M1未启用跨队合同。</p></div>
<div class="panel" id="marketpanel" style="margin-top:16px;display:none"><h2>M2跨队服务与实际验收</h2><p id="marketstates"></p><p id="marketresource"></p><p id="marketreason"></p><table><thead><tr><th>决策者</th><th>合法候选</th><th>预测按期量</th><th>预测总逾期</th><th>预测主动工作</th><th>完成时刻之和</th></tr></thead><tbody id="marketutilities"></tbody></table><p style="font-size:12px;color:#607068">仅比较受影响任务，已完成或未变任务抵消。主动工作包含移动、观察和装卸，不表示能耗；前三项相同时优先更早完成。预测不等于实际验收。</p></div>
<div class="panel" style="margin-top:16px"><h2>B1本地周期诊断</h2><p id="diagnostic"></p></div>
<div class="panel" style="margin-top:16px"><h2>已发生的关键事件</h2><div id="timeline"></div></div>
<footer id="provenance"></footer></main>
<script>
const data=__DATA__,c=data.card,e=data.events,tr=data.trajectory;
const $=id=>document.getElementById(id),ctx=$('map').getContext('2d');let time=0,playing=false;
$('identity').textContent=data.manifest.run_id+' ｜ '+(data.manifest.external_witness?'外部指定候选执行校准；不是策略自动搜索':data.decisions.length?data.manifest.policy+' 有界候选搜索与实际交接':'P0 固定分工基础闭环；合法候选比较尚未完成');
if(c.initial_completed){$('identity').textContent+=' ｜ 给定历史检查点：负时间完成项不计作本轮新成果'}
if(c.m2){$('marketpanel').style.display='block';$('contractmode').textContent='M2使用同一真实消息网络交换未来预约；R5报告实际送达并合格后才兑现服务。';$('identity').textContent+=' ｜ 六实体完整前缀 · M2图模型';}
if(data.manifest.fault_injection){const f=data.manifest.fault_injection;$('identity').textContent+=' ｜ 独立故障例：'+(f.radio_outage_ms?f.radio_outage_ms.map(t=>t/1000).join('—')+'s 全链路暂时中断':f.t_ms/1000+'s '+f.nodes.join('—')+'临时断联')+'，不计入冻结矩阵'}
$('provenance').textContent='证据来源：events.jsonl / trajectory.csv / scenario.json。代码 '+data.manifest.code_revision.slice(0,12)+'；题卡 SHA256 '+data.manifest.card_file_sha256+'。未启动 ROS/Gazebo，未进行物理碰撞或无线性能验收。';
const labels={report_rejected:'取样前报告不合格',observation_completed:'现场观察完成',message_arrived:'消息实际送达',load_started:'合法取样开始',delivery:'载荷实际交付',inspection:'巡检验收',report_delivery:'巡检报告送达',self_collection_infeasible:'自行带回报告无法保鲜',channel_enter:'进入共享通道',channel_cleared:'通道实际清空',role_active:'服务岗位到位',role_state:'岗位协议更新',service_edge_active:'新观察服务实际可用',reconfiguration_committed:'提交消息已发出',reconfiguration_aborted:'重构中止',message_failed:'消息投递失败'};
const px=(x)=>55+(x-1)*46,py=(y)=>205-y*19;
Object.assign(labels,{rolling_plan_selected:'双任务边界修复计划已选',remaining_plan_selected:'剩余任务计划已选',release_requested:'请求旧岗位实际释放',commitment_released:'执行者已退出旧承诺',release_acknowledged:'旧承诺释放回执实际到达',release_complete:'所需旧承诺已确认释放',release_refused:'持有货物，拒绝释放',protocol_retry:'同一提议的协议重试',fault_boundary:'通信故障边界'});
Object.assign(labels,{contract_state:'本机合同状态更新',contract_decision:'本机比较合同收益',slot_exchange_committed:'入口实际交换预约归属',service_state:'红方观察服务执行状态'});
function draw(){ctx.clearRect(0,0,800,410);ctx.font='14px sans-serif';
if(c.geometry){for(const box of c.geometry.obstacles){const lo=box.minimum,hi=box.maximum;ctx.fillStyle=box.radio_opaque?'#a7a39a':'#d5c1a0';ctx.fillRect(px(lo[0]),py(hi[1]),Math.max(3,px(hi[0])-px(lo[0])),py(lo[1])-py(hi[1]));}const d=c.geometry.device;ctx.fillStyle='#b83762';ctx.fillRect(px(d[0])-4,py(d[1])-4,8,8);ctx.fillText('观测目标',px(d[0])+7,py(d[1])+38);}
for(const [a,b,len,mode] of c.edges){const p=c.nodes[a],q=c.nodes[b],poly=c.geometry?.edge_polylines?.[a+'>'+b]||c.geometry?.edge_polylines?.[b+'>'+a]||[p,q];ctx.strokeStyle=mode==='air'?'#aab9b3':((a==='E'&&b==='W')?'#c18e4b':'#cbd3cf');ctx.lineWidth=a==='E'&&b==='W'?9:3;ctx.setLineDash(mode==='air'?[7,6]:[]);ctx.beginPath();poly.forEach((v,i)=>i?ctx.lineTo(px(v[0]),py(v[1])):ctx.moveTo(px(v[0]),py(v[1])));ctx.stroke();}ctx.setLineDash([]);
for(const [n,p] of Object.entries(c.nodes)){ctx.fillStyle='#c1cbc5';ctx.beginPath();ctx.arc(px(p[0]),py(p[1]),5,0,7);ctx.fill();ctx.fillStyle='#54645c';ctx.fillText(n,px(p[0])-4,py(p[1])+22)}
let groups={};for(const actor of Object.keys(c.fleet)){let r=null;for(let i=tr.length-1;i>=0;i--){if(tr[i].actor===actor&&tr[i].t_ms<=time){r=tr[i];break}}if(!r)continue;let key=r.x+','+r.y;let offset=groups[key]||0;groups[key]=offset+1;let x=px(r.x)+offset*21,y=py(r.y)-offset*7;ctx.fillStyle=actor[0]==='B'?'#276c9c':'#bd6048';ctx.beginPath();if(c.fleet[actor].mode==='air'){ctx.moveTo(x,y-11);ctx.lineTo(x+11,y+8);ctx.lineTo(x-11,y+8);ctx.closePath()}else ctx.arc(x,y,10,0,7);ctx.fill();ctx.fillStyle='#20302c';ctx.fillText(actor,x-10,y-17)}
}
function update(){time=Math.max(0,Math.min(c.end_ms,time));$('time').value=(time/1000).toFixed(1);$('clock').textContent='t = '+(time/1000).toFixed(1)+' s';draw();
const before=e.filter(x=>x.t_ms<=time);const significant=before.filter(x=>labels[x.kind]);$('timeline').replaceChildren(...significant.slice(-16).reverse().map(x=>{let d=document.createElement('div');d.textContent=(x.t_ms/1000).toFixed(1)+'s  '+x.actor+'  '+labels[x.kind]+(x.task_id?' / '+x.task_id:'');return d}));
const diagnostic=data.diagnostics.filter(x=>x.t_ms<=time).at(-1);$('diagnostic').textContent=diagnostic?JSON.stringify(diagnostic):'此时尚无周期诊断记录。诊断只使用本地状态和实际收到的消息，不代表已实现完整滚动重规划。';
const report=before.filter(x=>x.actor==='B1'&&(x.kind==='message_arrived'&&x.payload.payload?.subject_id==='device'||x.kind==='observation_completed')).at(-1);
const r=report?(report.payload.report||report.payload.payload):null;
$('report').replaceChildren();let line=document.createElement('div');line.textContent=r?'B1持有报告：采集 '+(r.sampled_at/1000).toFixed(1)+'s；当前年龄 '+((time-r.sampled_at)/1000).toFixed(1)+'s；τ = '+(c.tau_ms/1000)+'s':'B1 尚未收到本轮新报告';$('report').append(line);
const reject=before.filter(x=>x.kind==='report_rejected').at(-1),load=before.filter(x=>x.kind==='load_started').at(-1);let status=document.createElement('div');status.className='status';status.textContent=load?'最近合法取样：'+load.actor+' / '+load.task_id+'，t='+load.t_ms/1000+'s，报告年龄 '+load.payload.report_age_ms/1000+'s':reject?'已拒绝不合格报告；正在重新获取观察':'等待合格观察与真实送达';$('report').append(status);
$('tasks').replaceChildren(...c.tasks.map(task=>{const completed=before.find(x=>x.task_id===task.id&&['delivery','inspection','report_delivery'].includes(x.kind)),prior=c.initial_completed?.[task.id];let row=document.createElement('tr');for(const value of [task.id,task.deadline_ms/1000+'s',prior?prior.completed_ms/1000+'s（给定）':completed?completed.t_ms/1000+'s':'—',prior?'检查点前已完成':completed?(completed.payload.on_time?'按期':'逾期'):(time>task.deadline_ms?'未按期':'进行中')]){let cell=document.createElement('td');cell.textContent=value;row.append(cell)}return row}));
const decision=data.decisions.filter(x=>x.t_ms<=time).at(-1);const chosen=decision?decision.candidates.find(x=>x.id===decision.chosen):null;
$('decision').textContent=chosen?'已选候选 '+chosen.id+'：'+chosen.assignment+' / '+chosen.support+' / '+chosen.route+' / '+chosen.information+'；实际评价 '+decision.distinct_evaluated+' 个候选。空中接触预测需真实确认后兑现。':'当前尚未选择新安排。旧服务：B2观察并向B1送信；B1运输，B3巡检。';
$('roles').replaceChildren(...['B1','B2','B3'].map(actor=>{let states=before.filter(x=>x.kind==='role_state'&&(x.payload.provider?x.payload.provider===actor:x.actor===actor));let last=states.at(-1),row=document.createElement('tr');for(const value of [actor,last?last.payload.role:c.fleet[actor].role,last?last.payload.state:'原岗位',last?last.t_ms/1000+'s':'0s']){let cell=document.createElement('td');cell.textContent=value;row.append(cell)}return row}));
let active=before.filter(x=>x.kind==='service_edge_active');$('edges').textContent=active.length?'真实可用的新服务：'+active.map(x=>x.payload.provider+' → '+x.actor+'，采集 '+x.payload.sampled_at/1000+'s / 接收并检查 '+x.t_ms/1000+'s').join('；'):'尚无新观察服务完成接收验收；岗位确认或READY不代表报告已经可用。';
if(c.m2){
const fulfillment=before.find(x=>x.actor==='B1'&&x.kind==='contract_state'&&x.payload.state==='FULFILLED');
if(fulfillment)$('edges').textContent='跨队服务 R5 → B1 已实际验收：采集 '+fulfillment.payload.sampled_at/1000+'s，收到并验收 '+fulfillment.t_ms/1000+'s。';
const states=['B1','R1'].map(actor=>before.filter(x=>x.actor===actor&&x.kind==='contract_state').at(-1));
$('marketstates').textContent=states.map((x,i)=>(i?'R1':'B1')+'：'+(x?x.payload.state+'（'+x.t_ms/1000+'s）':'IDLE')).join(' ｜ ');
const grants=before.filter(x=>x.kind==='reservation_granted'&&x.payload.exchangeable),swap=before.filter(x=>x.kind==='slot_exchange_committed').at(-1);
$('marketresource').textContent='入口裁判归属（策略需等待消息）：'+grants.map(x=>x.payload.start/1000+'—'+x.payload.end/1000+'s → '+(swap?swap.payload.owners[x.payload.slot_id]:x.actor)).join('；');
const reasons=states.filter(x=>x?.payload.reason).map(x=>x.actor+'：'+x.payload.reason);$('marketreason').textContent=reasons.join('；');
let utilityRows=[];for(const actor of ['B1','R1']){const decision=before.filter(x=>x.kind==='contract_decision'&&x.actor===actor).at(-1);if(decision)for(const option of decision.payload.candidates){const u=option.utility;utilityRows.push([actor,({independent:'独立执行',release_without_service:'仅让行不取服务',exchange:'时隙换观察'})[option.id]||option.id,u[0],(-u[1]/1000)+'s',(-u[2]/1000)+'s',(-u[3]/1000)+'s']);}}
$('marketutilities').replaceChildren(...utilityRows.map(values=>{let row=document.createElement('tr');for(const value of values){let cell=document.createElement('td');cell.textContent=value;row.append(cell)}return row}));
}
}
document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{time=+b.dataset.t*1000;update()});$('play').onclick=()=>playing=!playing;const setTime=()=>{time=+$('time').value*1000;update()};$('time').onchange=setTime;$('time').oninput=setTime;$('reject').onclick=()=>{time=e.find(x=>x.kind==='report_rejected')?.t_ms||0;update()};$('sample').onclick=()=>{time=e.find(x=>x.kind==='load_started')?.t_ms||0;update()};$('handoff').onclick=()=>{time=e.find(x=>x.kind==='service_edge_active')?.t_ms||0;update()};$('finish').onclick=()=>{time=c.end_ms;update()};setInterval(()=>{if(playing){time+=200;update();if(time>=c.end_ms)playing=false}},100);update();
</script></html>'''

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir');args=p.parse_args();render(args.run_dir)
