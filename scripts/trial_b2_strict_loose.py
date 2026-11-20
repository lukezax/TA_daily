import csv, glob
from collections import OrderedDict

def f(row, key, default=None):
    try:
        v = row.get(key, '')
        return float(v) if v not in ('', None) else default
    except (ValueError, TypeError):
        return default

def lower(row, key):
    return str(row.get(key, '')).strip().lower() == 'true'

files = sorted(glob.glob('reports/b2_filtered_*.csv'))
print(f'现有 B2 CSV 文件数: {len(files)}  日期范围: {files[0].split("_")[-1].split(".")[0]} ~ {files[-1].split("_")[-1].split(".")[0]}')

candidates = [('现状 J_LAST<13', 13.0), ('方案A J_LAST<0', 0.0), ('方案B J_LAST<-13', -13.0), ('方案C J_LAST<-20', -20.0)]
totals = OrderedDict((name, {'strict':0,'loose':0,'violation':0}) for name,_ in candidates)
reported_loose = reported_strict = 0
recomputed_loose = 0
rows_with_data = 0

for fp in files:
    for row in csv.DictReader(open(fp, encoding='utf-8')):
        jl = f(row, 'B2_J_LAST'); j = f(row, 'B2_J')
        chg = f(row, 'B2_涨幅%'); vr = f(row, 'B2_放量比')
        close = f(row, '收盘价'); zxdkx = f(row, 'B2_ZXDKX'); zxdq = f(row, 'B2_ZXDQ')
        shadow = f(row, 'B2_上影线比')
        if any(v is None for v in (jl, j, chg, vr, close, zxdkx, zxdq, shadow)):
            continue
        rows_with_data += 1
        cond2 = chg > 3.95
        cond3 = vr > 1
        cond4 = j < 55
        cond5 = lower(row, 'B2_收阳') and shadow < 0.2
        cond6 = close > zxdkx
        cond7 = zxdq > zxdkx
        base = cond2 and cond3 and cond4
        loose = jl < 0 and base
        recomputed_loose += int(loose)
        reported_loose += int(str(row.get('B2宽松','')).strip() == '符合')
        reported_strict += int(str(row.get('B2严格','')).strip() == '符合')
        for name, th in candidates:
            strict = jl < th and base and cond5 and cond6 and cond7
            totals[name]['strict'] += int(strict)
            totals[name]['loose'] += int(loose)
            totals[name]['violation'] += int(strict and not loose)

print(f'有效数据行(全历史): {rows_with_data}')
print(f'报告口径: 严格={reported_strict}, 宽松={reported_loose}')
print(f'重算宽松: {recomputed_loose}  (与报告差异 {recomputed_loose-reported_loose})')
print()
print('候选口径试算（严格应满足 ⊆ 宽松，violation 应为 0）:')
for name, _ in candidates:
    t = totals[name]
    ratio = t['strict']/t['loose']*100 if t['loose'] else 0
    print(f'  {name:22s} 严格={t["strict"]:5d}  宽松={t["loose"]:5d}  严格占比={ratio:5.1f}%  严格但非宽松={t["violation"]:4d}')

# 最近 5 个文件单独看
print('\n最近 5 份 CSV 明细:')
for fp in files[-5:]:
    s13=s0=sm13=loose=0
    for row in csv.DictReader(open(fp, encoding='utf-8')):
        jl=f(row,'B2_J_LAST'); j=f(row,'B2_J'); chg=f(row,'B2_涨幅%'); vr=f(row,'B2_放量比')
        close=f(row,'收盘价'); zxdkx=f(row,'B2_ZXDKX'); zxdq=f(row,'B2_ZXDQ'); sh=f(row,'B2_上影线比')
        if any(v is None for v in (jl,j,chg,vr,close,zxdkx,zxdq,sh)): continue
        base = chg>3.95 and vr>1 and j<55
        extra = lower(row,'B2_收阳') and sh<0.2 and close>zxdkx and zxdq>zxdkx
        loose += int(jl<0 and base)
        s13 += int(jl<13 and base and extra)
        s0 += int(jl<0 and base and extra)
        sm13 += int(jl<-13 and base and extra)
    print(f'  {fp.split("/")[-1]}: 宽松={loose}, 严格现状={s13}, 严格方案A={s0}, 严格方案B={sm13}')
