"""Find every parking bay in the Pexels lot: parked cars (detector) -> rows -> painted bay lines per row."""
import sys, json, cv2, numpy as np
sys.path.insert(0, '/Users/hossam/hbh/vigil/backend')
from vigil.perception.detector import get_coco

SRC = '/Users/hossam/hbh/vigil/brand/pexels/lot_stable.mp4'
cap = cv2.VideoCapture(SRC); frames = []
while True:
    ok, f = cap.read()
    if not ok: break
    frames.append(f)

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    return i / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i + 1e-9)

def detect(img, nx=6, ny=4):
    H, W = img.shape[:2]; out = []
    tw, th = W / nx, H / ny
    for j in range(ny):
        for i in range(nx):
            x0, y0 = int(max(0, i*tw - tw*0.15)), int(max(0, j*th - th*0.15))
            x1, y1 = int(min(W, (i+1)*tw + tw*0.15)), int(min(H, (j+1)*th + th*0.15))
            for d in get_coco().detect(img[y0:y1, x0:x1], {'car': ['car', 'truck']}, threshold=0.25):
                b = d.box
                out.append([x0+b[0]*(x1-x0), y0+b[1]*(y1-y0), x0+b[2]*(x1-x0), y0+b[3]*(y1-y0), float(d.conf)])
    keep = []
    for b in sorted(out, key=lambda x: -x[4]):
        if all(iou(b, k) < 0.4 for k in keep): keep.append(b)
    return keep

samples = [(k, detect(frames[k])) for k in range(0, len(frames), 30)]   # once a second
print('cars per sample', [len(s) for _, s in samples][:6])
# stationary cars: clusters present in >= 3 consecutive samples
clusters = []
for _, s in samples:
    for b in s:
        for c in clusters:
            if iou(b, c['box']) > 0.5:
                break
        else:
            clusters.append({'box': b[:4]})
for c in clusters:
    pres = [max([iou(c['box'], x) for x in s] + [0]) > 0.5 for _, s in samples]
    best = cur = 0
    for p in pres:
        cur = cur + 1 if p else 0; best = max(best, cur)
    c['pres'] = pres; c['run'] = best
parked = [c for c in clusters if c['run'] >= 3]
print('parked cars (stationary >=3 s, any time):', len(parked))
json.dump({'parked': [{'box': c['box'], 'pres': c['pres']} for c in parked]}, open('/Users/hossam/hbh/vigil/brand/parked.json', 'w'))
img = frames[0].copy()
for c in parked:
    x0, y0, x1, y1 = [int(v) for v in c['box']]
    cv2.rectangle(img, (x0, y0), (x1, y1), (255, 160, 0) if all(c['pres']) else (0, 0, 255), 2)
cv2.imwrite('/Users/hossam/hbh/vigil/brand/parked.jpg', cv2.resize(img, (1600, 900)), [cv2.IMWRITE_JPEG_QUALITY, 82])

