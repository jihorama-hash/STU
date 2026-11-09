"""Browser label editor restricted to the approved TASK-009 frame list."""
from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from roundabout.site_finetune_labels import (  # noqa: E402
    CLASS_IDS,
    LabelValidationError,
    assert_frame_allowed,
    load_frame_whitelist,
    load_label_file,
    mask_outside_polygon,
    merge_boxes,
    polygon_from_mask,
    validate_box_in_polygon,
    validate_label_record,
)


PAGE = r"""<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TASK-009 학습 라벨</title>
<style>
body{margin:0;background:#15171b;color:#eee;font:15px system-ui}main{width:max-content;min-width:100%;margin:0;padding:12px;box-sizing:border-box}
#workspace{display:grid;grid-template-columns:1280px minmax(360px,520px);gap:12px;align-items:start;width:max-content}header,section{background:#20242a;padding:10px;margin-bottom:8px;border-radius:6px}button,select,input{padding:7px;margin:3px;background:#303741;color:#eee;border:1px solid #687080;border-radius:4px}header{width:1812px;box-sizing:border-box;font-size:12px;padding:8px}header button,header select,header input{font-size:12px;padding:4px;margin:2px}.toolbar{display:flex;align-items:center;gap:3px;flex-wrap:nowrap;white-space:nowrap;min-height:32px}.toolbar .spacer{flex:1}.toolbar .save-button{background:#245d37;border-color:#65b87d;font-weight:700;padding:6px 18px;font-size:14px}
#visualPanel{padding:0;margin:0}#viewport{width:1280px;max-height:75vh;overflow:auto;background:#111}#stage{position:relative;width:100%;aspect-ratio:16/9;background:#333;touch-action:none}#frame{width:100%;height:100%;display:block}#boxes{position:absolute;inset:0;width:100%;height:100%}.box{fill:var(--box-color);fill-opacity:.25;stroke:var(--box-color);stroke-width:2.5;vector-effect:non-scaling-stroke;cursor:move}.box.ignore{fill:#ff9900;stroke:#ffa500}.draft{stroke-dasharray:8 5}.box.active{stroke:#fff;stroke-width:4.5;fill-opacity:.6}.box-tag{font: bold 32px sans-serif;paint-order:stroke;stroke:#111;stroke-width:6px;fill:white;pointer-events:all;cursor:pointer}.handle{fill:#fff;stroke:#111;stroke-width:8;vector-effect:non-scaling-stroke;cursor:nwse-resize}#boxes.hide-numbers .box-tag{display:none}#boxes.hide-bounds .box.saved,#boxes.hide-bounds .handle{display:none}#objectPanel{max-height:75vh;overflow:auto;margin:0}#list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px}.item{display:flex;flex-wrap:wrap;align-items:center;align-content:flex-start;gap:1px;min-width:0;background:#303741;padding:3px;border:2px solid transparent;scroll-margin:12px;font-size:11px;overflow:hidden}.item.active{border-color:#fff;background:#17404a}.item input[type=number]{width:43px!important;box-sizing:border-box;padding:2px;margin:1px;font-size:10px}.item input:not([type=number]){max-width:110px;box-sizing:border-box;padding:3px;margin:1px;font-size:10px}.item input[type=checkbox]{width:14px;height:14px}.item button,.item select{box-sizing:border-box;max-width:100px;padding:3px;margin:1px;font-size:10px}.swatch{display:inline-block;width:10px;height:10px;margin-right:2px;border-radius:2px;vertical-align:middle}.draw{stroke:#ff00ff;stroke-width:5;fill:#ff00ff30;vector-effect:non-scaling-stroke}
</style><main><header><b>TASK-009 학습 라벨 편집기</b>
<div class="toolbar"><button onclick="move(-1)">이전</button><button onclick="move(1)">다음</button><span id="where"></span>
<button onclick="setZoom(1)">화면 맞춤</button><button onclick="setZoom(1.5)">확대 150%</button><button onclick="setZoom(2)">확대 200%</button><button onclick="setZoom(zoom/1.25)">−</button><button onclick="setZoom(zoom*1.25)">+</button><span id="zoomLabel">100%</span><span class="spacer"></span><button class="save-button" onclick="saveAll()">저장</button><span id="status"></span></div>
<div class="toolbar"><button onclick="stepObject(-1)">이전 객체</button><button onclick="stepObject(1)">다음 객체</button><span id="objectWhere"></span><button onclick="clearActiveObject()">선택 해제</button>
<label><input type="checkbox" id="showNumbers" checked onchange="toggleOverlay()"> 번호</label><label><input type="checkbox" id="showBounds" checked onchange="toggleOverlay()"> 경계</label><span>모서리 드래그: 크기 조정 · 박스 안 드래그: 이동</span>
<select id="newClass"><option>person</option><option>bicycle</option><option>car</option><option>motorcycle</option><option>bus</option><option>truck</option></select><label><input type="checkbox" id="newIgnore"> ignore</label><input id="newAttrs" placeholder="umbrella;pm;truncated">
<button onclick="mergeSelected('motorcycle')">합치기 → motorcycle</button><button onclick="mergeSelected('bicycle')">→ bicycle</button></div></header>
<div id="workspace"><section id="visualPanel"><div id="viewport"><div id="stage"><img id="frame"><svg id="boxes" viewBox="0 0 3840 2160" preserveAspectRatio="none" onpointerdown="down(event)" onpointermove="drag(event)" onpointerup="up(event)"><rect id="newBox" class="draw" visibility="hidden"/></svg></div></div></section>
<section id="objectPanel"><b>객체 목록</b><div id="list"></div></section></div></main>
<script>
let state=null,idx=0,start=null,editDrag=null,selected=new Set(),activeId=null,zoom=1;const $=id=>document.getElementById(id);const classIds={person:0,bicycle:1,car:2,motorcycle:3,bus:5,truck:7};
async function api(path,body){let r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});let j=await r.json();if(!r.ok)throw Error(j.error||r.statusText);return j}
async function load(){try{state=await api('/api/state?index='+idx);idx=state.index;selected.clear();activeId=null;$('where').textContent=`${idx+1}/${state.count} · ${state.clip_id} frame ${state.frame_index} (${state.split})`;$('frame').src='/api/image?index='+idx;render();$('status').textContent=''}catch(e){$('status').textContent=e.message}}
function setZoom(value){zoom=Math.max(1,Math.min(3,value));const width=Math.min(1280,$('viewport').clientWidth)*zoom;$('stage').style.width=width+'px';$('zoomLabel').textContent=Math.round(zoom*100)+'%'}
function toggleOverlay(){$('boxes').classList.toggle('hide-numbers',!$('showNumbers').checked);$('boxes').classList.toggle('hide-bounds',!$('showBounds').checked)}
function activeIndex(){return state.boxes.findIndex(b=>b.object_id===activeId)}
function clearActiveObject(){activeId=null;$('objectWhere').textContent='';render()}
function stepObject(delta){if(!state.boxes.length)return;let i=activeIndex();i=(i+delta+state.boxes.length)%state.boxes.length;selectObject(state.boxes[i].object_id)}
function selectObject(id,scroll=true){activeId=id;render();const i=activeIndex();$('objectWhere').textContent=i>=0?`객체 ${i+1}/${state.boxes.length}`:'';if(scroll){const row=document.querySelector(`[data-object-id="${CSS.escape(id)}"]`);row?.scrollIntoView({behavior:'smooth',block:'nearest'})}}
function render(){let svg=$('boxes');svg.querySelectorAll('.saved,.tag-bg,.box-tag,.handle').forEach(x=>x.remove());$('list').replaceChildren();state.boxes.forEach((b,i)=>{let color=`hsl(${(i*137.508)%360} 95% 62%)`;let r=document.createElementNS('http://www.w3.org/2000/svg','rect');r.setAttribute('x',b.x1);r.setAttribute('y',b.y1);r.setAttribute('width',b.x2-b.x1);r.setAttribute('height',b.y2-b.y1);r.style.setProperty('--box-color',color);r.setAttribute('class','box saved '+(b.ignore?'ignore ':'')+(b.label_source==='model_draft'?'draft ':'')+(activeId===b.object_id?'active':''));r.dataset.i=i;svg.append(r);let tag=document.createElementNS('http://www.w3.org/2000/svg','text');tag.setAttribute('x',Math.max(0,b.x1));tag.setAttribute('y',Math.max(64,b.y1+64));tag.setAttribute('class','box-tag');tag.dataset.i=i;tag.textContent=String(i+1);svg.append(tag);if(activeId===b.object_id){for(const [corner,x,y] of [['nw',b.x1,b.y1],['ne',b.x2,b.y1],['sw',b.x1,b.y2],['se',b.x2,b.y2]]){let h=document.createElementNS('http://www.w3.org/2000/svg','circle');h.setAttribute('cx',x);h.setAttribute('cy',y);h.setAttribute('r',30);h.setAttribute('class','handle');h.dataset.i=i;h.dataset.corner=corner;svg.append(h)}}
let d=document.createElement('div');d.className='item '+(activeId===b.object_id?'active':'');d.dataset.objectId=b.object_id;d.onclick=e=>{if(!e.target.closest('input,button,select'))selectObject(b.object_id,false)};let check=document.createElement('input');check.type='checkbox';check.checked=selected.has(b.object_id);check.title='합칠 객체 선택';check.onchange=()=>check.checked?selected.add(b.object_id):selected.delete(b.object_id);let swatch=document.createElement('span');swatch.className='swatch';swatch.style.background=color;let cls=document.createElement('select');['person','bicycle','car','motorcycle','bus','truck'].forEach(c=>{let o=document.createElement('option');o.text=c;o.selected=c===b.class_name;cls.append(o)});let ign=document.createElement('input');ign.type='checkbox';ign.checked=b.ignore;let attrs=document.createElement('input');attrs.value=(b.attributes||[]).join(';');attrs.placeholder='umbrella;pm;truncated';let coords=['x1','y1','x2','y2'].map(k=>{let n=document.createElement('input');n.type='number';n.step='1';n.value=b[k];n.title=k;n.style.width='76px';return n});let save=document.createElement('button');save.textContent='적용';save.onclick=()=>update(i,{x1:+coords[0].value,y1:+coords[1].value,x2:+coords[2].value,y2:+coords[3].value,class_name:cls.value,class_id:classIds[cls.value],ignore:ign.checked,attributes:attrs.value.split(';').filter(Boolean),label_source:'manual',revision_action:'adjusted'});let del=document.createElement('button');del.textContent='삭제';del.onclick=()=>action({action:'delete',object_id:b.object_id});d.append(check,swatch,document.createTextNode(` #${i+1} ${b.class_name} · `),cls,document.createTextNode(' ignore '),ign,attrs,...coords,save,del);$('list').append(d)});let i=activeIndex();$('objectWhere').textContent=i>=0?`객체 ${i+1}/${state.boxes.length}`:''}
async function action(v){try{state=await api('/api/action',{...v,index:idx});render();$('status').textContent='변경됨 · 저장 전'}catch(e){$('status').textContent=e.message}}
function update(i,patch){action({action:'update',object_id:state.boxes[i].object_id,patch})}
function point(e){let p=$('boxes').createSVGPoint();p.x=e.clientX;p.y=e.clientY;p=p.matrixTransform($('boxes').getScreenCTM().inverse());return [Math.max(0,Math.min(3840,p.x)),Math.max(0,Math.min(2160,p.y))]}
function down(e){let p=point(e);if(e.target.classList.contains('box-tag')){selectObject(state.boxes[Number(e.target.dataset.i)].object_id);return}if(e.target.classList.contains('handle')||e.target.classList.contains('saved')){let i=Number(e.target.dataset.i),b=state.boxes[i];activeId=b.object_id;$('boxes').setPointerCapture(e.pointerId);editDrag={i,mode:e.target.classList.contains('handle')?'resize':'move',corner:e.target.dataset.corner||'',origin:p,initial:{x1:b.x1,y1:b.y1,x2:b.x2,y2:b.y2}};render();return}start=p;$('boxes').setPointerCapture(e.pointerId);$('newBox').setAttribute('visibility','visible')}
function draggedBox(p){let d=editDrag,o=d.initial;if(d.mode==='move'){let dx=p[0]-d.origin[0],dy=p[1]-d.origin[1];dx=Math.max(-o.x1,Math.min(3840-o.x2,dx));dy=Math.max(-o.y1,Math.min(2160-o.y2,dy));return{x1:o.x1+dx,y1:o.y1+dy,x2:o.x2+dx,y2:o.y2+dy}}let b={...o},left=d.corner.includes('w'),top=d.corner.includes('n');if(left)b.x1=Math.max(0,Math.min(o.x2-2,p[0]));else b.x2=Math.min(3840,Math.max(o.x1+2,p[0]));if(top)b.y1=Math.max(0,Math.min(o.y2-2,p[1]));else b.y2=Math.min(2160,Math.max(o.y1+2,p[1]));return b}
function drag(e){let p=point(e);if(editDrag){let b=draggedBox(p),i=editDrag.i,r=document.querySelector(`#boxes rect.saved[data-i="${i}"]`);if(r){r.setAttribute('x',b.x1);r.setAttribute('y',b.y1);r.setAttribute('width',b.x2-b.x1);r.setAttribute('height',b.y2-b.y1)}let t=document.querySelector(`#boxes .box-tag[data-i="${i}"]`);if(t){t.setAttribute('x',Math.max(0,b.x1));t.setAttribute('y',Math.max(64,b.y1+64))}document.querySelectorAll(`#boxes .handle[data-i="${i}"]`).forEach(h=>{let c=h.dataset.corner;h.setAttribute('cx',c.includes('w')?b.x1:b.x2);h.setAttribute('cy',c.includes('n')?b.y1:b.y2)});return}if(!start)return;$('newBox').setAttribute('x',Math.min(start[0],p[0]));$('newBox').setAttribute('y',Math.min(start[1],p[1]));$('newBox').setAttribute('width',Math.abs(start[0]-p[0]));$('newBox').setAttribute('height',Math.abs(start[1]-p[1]))}
async function up(e){if(editDrag){let d=editDrag,b=draggedBox(point(e)),old=d.initial;editDrag=null;if(['x1','y1','x2','y2'].some(k=>Math.abs(b[k]-old[k])>2)){let obj=state.boxes[d.i];await action({action:'update',object_id:obj.object_id,patch:{...b,class_id:obj.class_id,label_source:'manual',revision_action:'adjusted'}})}else render();return}if(!start)return;let p=point(e),b={x1:Math.min(start[0],p[0]),y1:Math.min(start[1],p[1]),x2:Math.max(start[0],p[0]),y2:Math.max(start[1],p[1])};start=null;$('newBox').setAttribute('visibility','hidden');if(b.x2-b.x1<2||b.y2-b.y1<2)return;await action({action:'add',box:b,class_name:$('newClass').value,ignore:$('newIgnore').checked,attributes:$('newAttrs').value.split(';').filter(Boolean)})}
async function mergeSelected(cls){await action({action:'merge',object_ids:[...selected],class_name:cls});selected.clear()}
async function move(n){if(!await saveAll())return;idx=Math.max(0,Math.min(state.count-1,idx+n));await load()}
async function saveAll(){try{await api('/api/action',{action:'save',index:idx});$('status').textContent='저장 완료';return true}catch(e){$('status').textContent='저장 실패: '+e.message;return false}}
setZoom(1);toggleOverlay();load();
</script>"""


class LabelState:
    def __init__(self, frame_list: Path, labels_path: Path, drafts_path: Path, mask_dir: Path,
                 video_dir: Path, radius: int) -> None:
        self.whitelist = load_frame_whitelist(frame_list)
        self.frames = sorted(self.whitelist)
        if not self.frames:
            raise ValueError("approved frame list is empty")
        self.labels_path = labels_path
        self.labels = load_label_file(labels_path if labels_path.exists() else drafts_path)
        self.mask_dir, self.video_dir, self.radius = mask_dir, video_dir, radius
        self.cache: dict[tuple[str, int], np.ndarray] = {}
        self.lock = threading.RLock()

    def frame_row(self, index: int) -> tuple[str, int, dict[str, str]]:
        clip, frame = self.frames[index]
        row = assert_frame_allowed(self.whitelist, clip, frame)
        return clip, frame, row

    @staticmethod
    def key(clip: str, frame: int) -> str:
        return f"{clip}@{frame}"

    def get_frame(self, index: int) -> np.ndarray:
        clip, frame_index, _ = self.frame_row(index)
        key = (clip, frame_index)
        if key in self.cache:
            return self.cache[key]
        cap = cv2.VideoCapture(str(self.video_dir / f"{clip}.MP4"))
        if not cap.isOpened():
            raise OSError(f"could not open {clip}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            raise OSError(f"could not read {clip}@{frame_index}")
        self.cache[key] = frame
        return frame

    def polygon(self, clip: str) -> np.ndarray:
        mask_id = "DJI_0483_Cut" if clip == "DJI_0483" else clip
        return polygon_from_mask(self.mask_dir / f"{mask_id}_roadway_mask.png", self.radius)

    def box_list(self, clip: str, frame: int) -> list[dict]:
        return self.labels["frames"].setdefault(self.key(clip, frame), {
            "clip_id": clip, "frame_index": frame, "split": self.whitelist[(clip, frame)]["split"],
            "width": 3840, "height": 2160, "objects": [],
        })["objects"]


class AnnotationServer(ThreadingHTTPServer):
    def __init__(self, address, state: LabelState):
        self.state = state
        super().__init__(address, AnnotationHandler)


class AnnotationHandler(BaseHTTPRequestHandler):
    server: AnnotationServer

    def log_message(self, *_args):
        pass

    def send_bytes(self, status: int, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status: int, payload: dict) -> None:
        self.send_bytes(status, "application/json; charset=utf-8",
                        json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.send_bytes(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        try:
            query = parse_qs(parsed.query)
            index = int(query.get("index", ["0"])[0])
            if not 0 <= index < len(self.server.state.frames):
                raise ValueError("frame index out of range")
            clip, frame, row = self.server.state.frame_row(index)
            boxes = self.server.state.box_list(clip, frame)
            if parsed.path == "/api/state":
                return self.send_json(200, {
                    "index": index, "count": len(self.server.state.frames),
                    "clip_id": clip, "frame_index": frame, "split": row["split"],
                    "boxes": boxes,
                })
            if parsed.path == "/api/image":
                image = mask_outside_polygon(
                    self.server.state.get_frame(index),
                    self.server.state.polygon(clip), boxes,
                )
                ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                return self.send_bytes(200, "image/jpeg", encoded.tobytes())
            return self.send_json(404, {"error": "not found"})
        except Exception as exc:
            return self.send_json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            payload = self.read_body()
            index = int(payload.get("index", 0))
            clip, frame, row = self.server.state.frame_row(index)
            boxes = self.server.state.box_list(clip, frame)
            action = payload.get("action")
            if action == "add":
                box = payload["box"]
                record = {
                    "object_id": f"{clip}_{frame}_{len(boxes)+1:02d}",
                    **{k: float(box[k]) for k in ("x1", "y1", "x2", "y2")},
                    "class_name": payload["class_name"],
                    "class_id": CLASS_IDS[payload["class_name"]],
                    "ignore": bool(payload.get("ignore", False)),
                    "attributes": payload.get("attributes", []),
                    "label_source": "manual", "revision_action": "new",
                }
                validate_label_record(record, 3840, 2160)
                validate_box_in_polygon(record, self.server.state.polygon(clip))
                boxes.append(record)
            elif action == "delete":
                self.server.state.labels["frames"][self.server.state.key(clip, frame)]["objects"] = [
                    b for b in boxes if b["object_id"] != payload["object_id"]
                ]
                boxes = self.server.state.labels["frames"][self.server.state.key(clip, frame)]["objects"]
            elif action == "update":
                target = next(b for b in boxes if b["object_id"] == payload["object_id"])
                target.update(payload["patch"])
                validate_label_record(target, 3840, 2160)
                validate_box_in_polygon(target, self.server.state.polygon(clip))
            elif action == "merge":
                updated = merge_boxes(boxes, payload["object_ids"], payload["class_name"])
                for record in updated:
                    validate_label_record(record, 3840, 2160)
                    validate_box_in_polygon(record, self.server.state.polygon(clip))
                self.server.state.labels["frames"][self.server.state.key(clip, frame)]["objects"] = updated
                boxes = updated
            elif action == "save":
                self.server.state.labels_path.parent.mkdir(parents=True, exist_ok=True)
                self.server.state.labels_path.write_text(
                    json.dumps(self.server.state.labels, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            else:
                raise ValueError("unknown action")
            return self.send_json(200, {
                "index": index, "count": len(self.server.state.frames),
                "clip_id": clip, "frame_index": frame, "split": row["split"], "boxes": boxes,
            })
        except Exception as exc:
            return self.send_json(400, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--frame-list", default="data/training_labels/site_finetune_r01_v1/frame_list.csv")
    parser.add_argument("--labels", default="data/training_labels/site_finetune_r01_v1/labels.json")
    parser.add_argument("--drafts", default="data/training_labels/site_finetune_r01_v1/model_drafts.json")
    parser.add_argument("--mask-dir", default="data/calibration/by_video")
    parser.add_argument("--video-dir", default="data/raw/before")
    parser.add_argument("--radius", type=int, default=200)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    # Use the generated analysis masks only if present; source masks remain untouched.
    state = LabelState(ROOT / args.frame_list, ROOT / args.labels, ROOT / args.drafts, ROOT / args.mask_dir,
                       ROOT / args.video_dir, args.radius)
    server = AnnotationServer((args.host, args.port), state)
    url = f"http://{args.host}:{args.port}/"
    print(f"TASK-009 labeler: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
