"""Check V2 tokens against the approved visual specification (stdlib only)."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'docs/design/v2-visual-baseline.md'
CSS = ROOT / 'v2/frontend/src/styles.css'


def specification(text, section):
    content = text.split('### ' + section + ' ', 1)[1].split('### ', 1)[0]
    result = {}
    for name, value in re.findall(r'\| `(--[\w-]+)` \| ([^|]+) \|', content):
        color = re.search(r'oklch\([^)]+\)', value)
        if color:
            result[name] = color[0]
        elif name == '--accent':
            result[name] = specification(text, '3.3')[name]
    return result


def check():
    spec, css = SPEC.read_text(encoding='utf-8'), CSS.read_text(encoding='utf-8')
    selectors = { '3.3': r':root\s*\{([^}]+)\}', '3.4': r'html\[data-theme="dark"\]\s*\{([^}]+)\}' }
    expected_names = set(specification(spec, '3.3'))
    if len(expected_names) != 21:
        raise ValueError('Expected the 21 approved color tokens')
    rows = {}
    for section, selector in selectors.items():
        expected = specification(spec, section)
        values = {}
        for block in re.findall(selector, css):
            values.update(re.findall(r'(--[\w-]+):\s*([^;]+);', block))
        if set(expected) != expected_names:
            raise ValueError('Light and dark token sets differ')
        for name, value in expected.items():
            if values.get(name) != value:
                raise ValueError(f'{section} {name}: expected {value}, got {values.get(name)}')
            offset = css.index(f'{name}: {value};', css.index('html[data-theme') if section == '3.4' else 0)
            rows.setdefault(name, []).append((value, css.count('\n', 0, offset) + 1))
    components = css.split('/* Components */', 1)[1]
    if re.search(r'#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(', components):
        raise ValueError('Component color literals must use semantic tokens')
    declarations = set(re.findall(r'(--[\w-]+)\s*:', css))
    references = set(re.findall(r'var\((--[\w-]+)', css))
    if references - declarations:
        raise ValueError(f'Undefined tokens: {sorted(references - declarations)}')
    for utility in ('focus-ring', 'row-hover', 'num', 'shadow-modal'):
        if '.' + utility not in css:
            raise ValueError(f'Missing utility: {utility}')
    print('| Token | Light OKLCH / line | Dark OKLCH / line |')
    print('|---|---|---|')
    for name, pair in rows.items():
        print(f'| `{name}` | `{pair[0][0]}` / L{pair[0][1]} | `{pair[1][0]}` / L{pair[1][1]} |')
    print('\nPASS: 42 color values, token references, component colors and four utilities.')


if __name__ == '__main__':
    try:
        check()
    except (ValueError, IndexError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
