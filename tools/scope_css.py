"""Begrenzt ein Stylesheet aus design/ auf einen Bereich (z. B. #bmcShell), damit es die übrige Oberfläche nicht verändert.
Aufruf: python3 tools/scope_css.py <quelle.css> '#bmcShell' > ausgabe.css"""
import sys


def scope_sel(sel, root):
    out = []
    for s in sel.split(','):
        s = s.strip()
        if s in (':root', 'body', 'html', 'html,body'):
            out.append(root)
        elif s == '*':
            out.append('%s,%s *' % (root, root))
        else:
            out.append(root + ' ' + s)
    return ','.join(out)


def scope(css, root):
    res, i = [], 0
    css = css.strip()
    while i < len(css):
        while i < len(css) and css[i] in ' \n\t':
            i += 1
        if i >= len(css):
            break
        if css.startswith('/*', i):
            i = css.index('*/', i) + 2
            continue
        if css.startswith('@media', i):
            j = css.index('{', i)
            depth, k = 1, j + 1
            while depth:
                depth += {'{': 1, '}': -1}.get(css[k], 0)
                k += 1
            res.append(css[i:j + 1] + scope(css[j + 1:k - 1], root) + '}')
            i = k
            continue
        j = css.index('{', i)
        k = css.index('}', j)
        res.append(scope_sel(css[i:j], root) + css[j:k + 1])
        i = k + 1
    return ''.join(res)


if __name__ == '__main__':
    print(scope(open(sys.argv[1], encoding='utf-8').read(), sys.argv[2]))
