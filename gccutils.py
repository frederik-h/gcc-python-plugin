import gcc

def get_src_for_loc(loc):
    # Given a gcc.Location, get the source line as a string
    import linecache
    return linecache.getline(loc.file, loc.line).rstrip()

def get_global_typedef(name):
    # Look up a typedef in global scope by name, returning a gcc.TypeDecl,
    # or None if not found
    for u in gcc.get_translation_units():
        for v in u.block.vars:
            if isinstance(v, gcc.TypeDecl):
                if v.name == name:
                    return v

def invoke_dot(dot):
    from subprocess import Popen, PIPE
    p = Popen(['dot', '-Tpng', '-o', 'test.png'],
              stdin=PIPE)
    p.communicate(dot.encode('ascii'))

    p = Popen(['eog', 'test.png'])
    p.communicate()
    

class DotPrettyPrinter:
    # Base class for various kinds of data visualizations that use graphviz
    # (aka ".dot" source files)
    def to_html(self, text):
        html_escape_table = {
            "&": "&amp;",
            '"': "&quot;",
            "'": "&apos;",
            ">": "&gt;",
            "<": "&lt;",
            
            # 'dot' doesn't seem to like these:
            '{': '\\{',
            '}': '\\}',
          }
        return "".join(html_escape_table.get(c,c) for c in str(text))

    def _dot_td(self, text, align="left", colspan=1, escape=1, bgcolor=None):
        if escape:
            text = self.to_html(text)
        attribs = 'align="%s" colspan="%i"' % (align, colspan)
        if bgcolor:
            attribs += ' bgcolor="%s"' % bgcolor
        return ('<td %s>%s</td>'
                % (attribs, text))

    def _dot_tr(self, td_text):
        return ('<tr>%s</tr>\n' % self._dot_td(td_text))


class CfgPrettyPrinter(DotPrettyPrinter):
    # Generate graphviz source for this gcc.Cfg instance, as a string
    def __init__(self, cfg):
        self.cfg = cfg

    def block_id(self, b):
        if b is self.cfg.entry:
            return 'entry'
        if b is self.cfg.exit:
            return 'exit'
        return 'block%i' % id(b)

    def block_to_dot_label(self, bb):
        # FIXME: font setting appears to work on my machine, but I invented
        # the attribute value; it may be exercising a failure path
        result = '<font face="monospace"><table cellborder="0" border="0" cellspacing="0">\n'
        result += '<tr> <td>BLOCK %i</td> <td></td> </tr>' % bb.index
        curloc = None
        if isinstance(bb.phi_nodes, list):
            for phi in bb.phi_nodes:
                result += '<tr><td></td>' + self.stmt_to_html(phi) + '</tr>'
        if isinstance(bb.gimple, list) and bb.gimple != []:
            for stmt in bb.gimple:
                if curloc != stmt.loc:
                    curloc = stmt.loc
                    result += ('<tr><td>' + self.to_html(get_src_for_loc(stmt.loc))
                               + '<br/>'
                               + (' ' * (stmt.loc.column-1)) + '^'
                               + '</td></tr>')
                    
                result += '<tr><td></td>' + self.stmt_to_html(stmt) + '</tr>'
        else:
            # (prevent graphviz syntax error for empty blocks):
            result += self._dot_tr(self.block_id(bb))
        result += '</table></font>\n'
        return result

    def stmt_to_html(self, stmt):
        text = str(stmt).strip()
        text = self.to_html(text)
        bgcolor = None

        # Work towards visualization of CPython refcounting rules.
        # For now, paint assignments to (PyObject*) vars and to ob_refcnt
        # fields, to highlight the areas needing tracking:
        # print 'stmt: %s' % stmt
        if hasattr(stmt, 'lhs'):
            # print 'stmt.lhs: %s' % stmt.lhs
            # print 'stmt.lhs: %r' % stmt.lhs
            if stmt.lhs:
                # print 'stmt.lhs.type: %s' % stmt.lhs.type

                # Color assignments to (PyObject *) in red:
                if str(stmt.lhs.type) == 'struct PyObject *':
                    bgcolor = 'red'

                # Color assignments to PTR->ob_refcnt in blue:
                if isinstance(stmt.lhs, gcc.ComponentRef):
                    # print(dir(stmt.lhs))
                    # print 'stmt.lhs.target: %s' % stmt.lhs.target
                    # print 'stmt.lhs.target.type: %s' % stmt.lhs.target.type
                    # (presumably we need to filter these to structs that are
                    # PyObject, or subclasses)
                    # print 'stmt.lhs.field: %s' % stmt.lhs.field
                    if stmt.lhs.field.name == 'ob_refcnt':
                        bgcolor = 'blue'

        return self._dot_td(text, escape=0, bgcolor=bgcolor)

    def edge_to_dot(self, e):
        if e.true_value:
            attrliststr = '[label = true]'
        elif e.false_value:
            attrliststr = '[label = false]'
        elif e.loop_exit:
            attrliststr = '[label = loop_exit]'
        elif e.fallthru:
            attrliststr = '[label = fallthru]'
        elif e.dfs_back:
            attrliststr = '[label = dfs_back]'
        else:
            attrliststr = ''
        return ('   %s -> %s %s;\n'
                % (self.block_id(e.src), self.block_id(e.dest), attrliststr))

    def to_dot(self):
        result = 'digraph G {\n'
        result += '  node [shape=record];\n'
        for block in self.cfg.basic_blocks:

            result += ('  %s [label=<%s>];\n'
                       % (self.block_id(block), self.block_to_dot_label(block)))

            for edge in block.succs:
                result += self.edge_to_dot(edge)
            # FIXME: this will have duplicates:
            #for edge in block.preds:
            #    result += edge_to_dot(edge)

        result += '}\n'
        return result

class TreePrettyPrinter(DotPrettyPrinter):
    # Generate a graphviz visualization of this gcc.Tree and the graphs of
    # nodes it references, as a string
    def __init__(self, root):
        print 'root: %s' % root
        assert isinstance(root, gcc.Tree)
        self.root = root

    def attr_to_str(self, name, value):
        if name == 'addr':
            return hex(value)
        if isinstance(value, str):
            return repr(value)
        return str(value)

    def label_for_tree(self, obj):
        result = '<table cellborder="0" border="0" cellspacing="0">\n'
        result += ('<tr> %s </tr>\n'
                   % (self._dot_td(obj, colspan=2)))
        #self._dot_td('')))
        for name, value in self.iter_attrs(obj):
            result += ('<tr> %s %s </tr>\n'
                       % (self._dot_td(name),
                          self._dot_td(self.attr_to_str(name, value))))
        result += '</table>\n'
        return result

    def iter_attrs(self, obj):
        # Iterate through the interesting attributes of the object:
        for name in dir(obj):
            # Ignore private and "magic" attributes:
            if name.startswith('_'):
                continue
            value = getattr(obj, name)
            # Ignore methods:
            if hasattr(value, '__call__'):
                continue
            #print 'attr %r    obj.%s: %r' % (name, name, value)
            yield (name, value)

    def tree_to_dot(self, obj):
        assert isinstance(obj, gcc.Tree)
        result = ('  %s [label=<%s>];\n'
                  % ('foo', self.label_for_tree(obj)))
        for name, value in self.iter_attrs(obj):
            print 'attr %r    obj.%s: %r' % (name, name, value)
        return result

    def to_dot(self):
        self.root.debug()
        result = 'digraph G {\n'
        result += '  node [shape=record];\n'
        result += self.tree_to_dot(self.root)
        result += '}\n'
        return result

def cfg_to_dot(cfg):
    pp = CfgPrettyPrinter(cfg)
    return pp.to_dot()


def tree_to_dot(tree):
    pp = TreePrettyPrinter(tree)
    return pp.to_dot()
