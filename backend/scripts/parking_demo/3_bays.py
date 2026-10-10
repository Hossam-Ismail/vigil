"""Bay layout for the whole lot: every spot a car is parked in during the clip, plus empty bays found along each
row of parked cars where the painted bay lines continue (gaps between cars and past the row ends)."""
import json, cv2, numpy as np
B = '/Users/hossam/hbh/vigil/brand/'
bg = cv2.imread(B + 'bg.png')
BAND = (0, 196, 1920, 1010)
hsv = cv2.cvtColor(bg, cv2.COLOR_BGR2HSV)
white = ((hsv[..., 2] > 170) & (hsv[..., 1] < 60)).astype(np.float32)
green = ((hsv[..., 0] > 30) & (hsv[..., 0] < 90) & (hsv[..., 1] > 60)).astype(np.float32)

def longest(p):
    b = c = 0
    for v in p:
        c = c + 1 if v else 0; b = max(b, c)
    return b

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    return i / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i + 1e-9)

def contains_center(a, b):
    cx, cy = (b[0]+b[2])/2, (b[1]+b[3])/2
    return a[0] < cx < a[2] and a[1] < cy < a[3]

# checked once by eye on the background frame: places the line rule accepts that are not bays
NOT_BAYS = [(710, 295), (630, 500), (960, 405), (1650, 350), (1812, 340), (1860, 335), (1590, 765), (552, 650), (1880, 550)]  # caravan-lane text, pay machine,
#   zebra crossing, road arrow, tree island, car parked across the island edge, car waiting in the aisle, road,
#   van stopped on the road edge
# 1. parked spots: detections stationary for >= 6 s, upright (bays here run top-to-bottom), inside the frame band
raw = [p for p in json.load(open(B + 'parked.json'))['parked'] if longest(p['pres']) >= 6]
raw = [p for p in raw if (p['box'][3]-p['box'][1]) >= 0.7*(p['box'][2]-p['box'][0])
       and p['box'][1] >= BAND[1]-15 and p['box'][3] <= BAND[3]+15]
# merge duplicates of the same spot (one car seen with slightly different boxes, or one car replacing another)
groups = []
for p in sorted(raw, key=lambda p: -longest(p['pres'])):
    for g in groups:
        if iou(g[0]['box'], p['box']) > 0.3 or contains_center(g[0]['box'], p['box']) and contains_center(p['box'], g[0]['box']):
            g.append(p); break
    else:
        groups.append([p])
spots = [list(np.median([q['box'] for q in g], axis=0)) for g in groups]
spots = [b for b in spots if not any(b[0] < px < b[2] and b[1] < py < b[3] for px, py in NOT_BAYS)]
print('parked spots', len(spots), 'from', len(raw), 'detections')

def line_at(x, y0, y1):
    """painted bay line near x: share of white pixels in the best 5-px column within +-6 px, middle 70% of the bay"""
    h = y1 - y0; a, b = int(y0 + 0.15*h), int(y1 - 0.15*h)
    x = int(x); cols = white[a:b, max(0, x-6):x+7].mean(0)
    return float(cols.max()) if cols.size else 0.0

# caravan bays (left lot, "CARAVANS ONLY"): long bays the row rule cannot infer, marked from their painted lines
CARAVAN = [[47, 350, 99, 494], [99, 352, 155, 494], [155, 356, 206, 494], [206, 356, 259, 494], [259, 372, 322, 500],
           [322, 378, 381, 505], [381, 380, 440, 510]]

def ok_empty(b):
    x0, y0, x1, y1 = [int(v) for v in b]
    if x0 < 0 or x1 > 1920 or y0 < BAND[1]-10 or y1 > BAND[3]+10:
        return False
    if green[y0:y1, x0:x1].mean() > 0.25:        # hedge or tree, not a bay
        return False
    h, w = y1 - y0, x1 - x0
    if white[y0 + h//6:y1 - h//6, x0 + w//5:x1 - w//5].mean() > 0.22:   # zebra crossing, lane text, road arrow
        return False
    if any(x0 < px < x1 and y0 < py < y1 for px, py in NOT_BAYS):
        return False
    return max(line_at(x0, y0, y1), line_at(x1, y0, y1)) >= 0.3 and min(line_at(x0, y0, y1), line_at(x1, y0, y1)) >= 0.12

# 2. rows: chain spots whose vertical extent overlaps strongly, left to right
rows = []
for s in sorted(spots, key=lambda b: (b[0]+b[2])/2):
    h = s[3]-s[1]
    best = None
    for r in rows:
        l = r[-1]; ov = min(l[3], s[3]) - max(l[1], s[1])
        dx = (s[0]+s[2])/2 - (l[0]+l[2])/2
        if ov > 0.6*min(h, l[3]-l[1]) and 0 < dx < 7*(s[2]-s[0]) and (best is None or dx < best[1]):
            best = (r, dx)
    (best[0].append(s) if best else rows.append([s]))
empties = []
for r in rows:
    if len(r) < 3:
        continue
    w = float(np.median([b[2]-b[0] for b in r]))
    dxs = [(b[0]+b[2])/2 - (a[0]+a[2])/2 for a, b in zip(r, r[1:])]
    pitch = [d for d in dxs if 0.8*w <= d <= 1.6*w]
    if len(pitch) < 2:
        continue
    pitch = float(np.median(pitch))
    new = []
    for a, b in zip(r, r[1:]):                               # gaps inside the row
        d = (b[0]+b[2])/2 - (a[0]+a[2])/2
        n = int(round(d / pitch)) - 1
        for k in range(1, n + 1) if d >= 1.5*pitch else []:
            f = k / (n + 1); cx = (a[0]+a[2])/2 + f*d
            y0 = a[1] + f*(b[1]-a[1]); y1 = a[3] + f*(b[3]-a[3])
            new.append([cx - pitch/2 + 2, y0, cx + pitch/2 - 2, y1])
    for end, sgn in ((r[0], -1), (r[-1], 1)):              # past the row ends while the lines continue
        cx = (end[0]+end[2])/2
        for k in range(1, 4):
            c = cx + sgn*k*pitch
            b = [c - pitch/2 + 2, end[1], c + pitch/2 - 2, end[3]]
            if not ok_empty(b) or any(iou(b, s) > 0.2 for s in spots):
                break
            new.append(b)
    for b in new:
        if ok_empty(b) and not any(iou(b, s) > 0.2 for s in spots + empties):
            empties.append(b)
# angled top-left row: the empty stretches between its parked cars, one car-width slot each
TOPLEFT = [[2, 226, 50, 274], [183, 236, 240, 285], [242, 244, 298, 293], [356, 256, 409, 303], [562, 272, 600, 318]]
for b in CARAVAN + TOPLEFT:
    if not any(contains_center(b, s) for s in spots):
        empties.append(b)
bays = spots + empties
print('rows', sum(len(r) >= 3 for r in rows), '| empty bays added', len(empties), '| total', len(bays))
json.dump({'bays': bays, 'parked_spots': len(spots)}, open(B + 'bays.json', 'w'))
img = bg.copy()
for i, b in enumerate(bays):
    x0, y0, x1, y1 = [int(v) for v in b]
    cv2.rectangle(img, (x0+1, y0+1), (x1-1, y1-1), (0, 255, 0) if i < len(spots) else (255, 160, 0), 2)
    cv2.putText(img, str(i), (x0+3, y0+14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
S = B + 'bays_'
cv2.imwrite(S + 'L3.jpg', img[196:1010, 0:1000]); cv2.imwrite(S + 'R3.jpg', img[196:1010, 920:1920])
cv2.imwrite(B + 'bays.jpg', cv2.resize(img, (1600, 900)), [cv2.IMWRITE_JPEG_QUALITY, 82])
