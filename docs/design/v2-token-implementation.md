# V2 Token 实施核对（#307）

规格：v2-visual-baseline.md §3.3–3.5。由 python scripts/check_v2_visual_tokens.py 核对，源码行为准；规格未修改。

| Token | Light OKLCH / line | Dark OKLCH / line |
|---|---|---|
| `--surface-base` | `oklch(0.984 0.003 248)` / L19 | `oklch(0.176 0.011 266)` / L45 |
| `--surface-card` | `oklch(1 0 0)` / L20 | `oklch(0.216 0.013 266)` / L46 |
| `--surface-inset` | `oklch(0.968 0.007 248)` / L21 | `oklch(0.256 0.014 266)` / L47 |
| `--surface-modal` | `oklch(1 0 0)` / L22 | `oklch(0.256 0.014 266)` / L48 |
| `--foreground` | `oklch(0.208 0.042 266)` / L23 | `oklch(0.955 0.008 256)` / L49 |
| `--muted-foreground` | `oklch(0.446 0.03 256)` / L24 | `oklch(0.72 0.02 256)` / L50 |
| `--faint` | `oklch(0.704 0.04 256)` / L25 | `oklch(0.56 0.022 256)` / L51 |
| `--border` | `oklch(0.869 0.022 253)` / L26 | `oklch(0.34 0.016 266)` / L52 |
| `--border-subtle` | `oklch(0.929 0.013 256)` / L27 | `oklch(0.29 0.014 266)` / L53 |
| `--primary` | `oklch(0.623 0.214 259)` / L28 | `oklch(0.71 0.15 255)` / L54 |
| `--primary-foreground` | `oklch(1 0 0)` / L29 | `oklch(0.16 0.03 266)` / L55 |
| `--success` | `oklch(0.627 0.17 149)` / L30 | `oklch(0.73 0.16 152)` / L56 |
| `--warning` | `oklch(0.646 0.153 61)` / L31 | `oklch(0.79 0.14 78)` / L57 |
| `--danger` | `oklch(0.577 0.245 27)` / L32 | `oklch(0.68 0.19 25)` / L58 |
| `--info` | `oklch(0.588 0.158 242)` / L33 | `oklch(0.72 0.13 238)` / L59 |
| `--tint-primary` | `oklch(0.972 0.012 251)` / L34 | `oklch(0.3 0.03 262)` / L60 |
| `--tint-success` | `oklch(0.963 0.021 155)` / L35 | `oklch(0.31 0.05 155)` / L61 |
| `--tint-warning` | `oklch(0.96 0.021 75)` / L36 | `oklch(0.32 0.05 75)` / L62 |
| `--tint-danger` | `oklch(0.945 0.021 22)` / L37 | `oklch(0.31 0.06 22)` / L63 |
| `--tint-info` | `oklch(0.954 0.017 232)` / L38 | `oklch(0.31 0.04 235)` / L64 |
| `--accent` | `oklch(0.585 0.223 285)` / L39 | `oklch(0.585 0.223 285)` / L65 |

PASS: 42 color values, token references, component colors and four utilities.

人工状态：浅色与深色视觉终验待 #310；本表仅证明实现值与规格一致。
