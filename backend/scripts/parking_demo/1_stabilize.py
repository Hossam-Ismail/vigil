"""Stabilize the drone clip to its first frame (so it behaves like a fixed camera)."""
import cv2, numpy as np
SRC = '/Users/hossam/hbh/vigil/brand/pexels/lot_1080.mp4'
OUT = '/Users/hossam/hbh/vigil/brand/pexels/lot_stable.mp4'
cap = cv2.VideoCapture(SRC); fps = cap.get(cv2.CAP_PROP_FPS)
ok, ref = cap.read()
orb = cv2.ORB_create(4000)
small = lambda im: cv2.cvtColor(cv2.resize(im, (960, 540)), cv2.COLOR_BGR2GRAY)
kr, dr = orb.detectAndCompute(small(ref), None)
bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
w = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*'mp4v'), fps, (1920, 1080))
w.write(ref)
shifts = []
while True:
    ok, f = cap.read()
    if not ok: break
    k, d = orb.detectAndCompute(small(f), None)
    m = sorted(bf.match(d, dr), key=lambda x: x.distance)[:800]
    src = np.float32([k[x.queryIdx].pt for x in m]) * 2
    dst = np.float32([kr[x.trainIdx].pt for x in m]) * 2
    A, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    shifts.append((round(float(A[0, 2]), 1), round(float(A[1, 2]), 1), round(float(np.degrees(np.arctan2(A[1, 0], A[0, 0]))), 2)))
    w.write(cv2.warpAffine(f, A, (1920, 1080), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE))
w.release()
s = np.array(shifts)
print('frames', len(shifts) + 1, '| drift dx range', s[:, 0].min(), s[:, 0].max(), '| dy range', s[:, 1].min(), s[:, 1].max(), '| rot', s[:, 2].min(), s[:, 2].max())
