from __future__ import generators
import autopath
import os, time, sys
import pygame
from pygame.locals import *
from pypy.translator.tool.pygame.drawgraph import GraphRenderer
from pypy.translator.tool.pygame.drawgraph import Node, Edge


METAKEYS = dict([
    (ident[len('KMOD_'):].lower(), getattr(pygame.locals, ident))
    for ident in dir(pygame.locals) if ident.startswith('KMOD_') and ident != 'KMOD_NONE'
])

if sys.platform == 'darwin':
    PMETA = 'lmeta', 'rmeta'
else:
    PMETA = 'lalt', 'ralt', 'lctrl', 'rctrl'

METAKEYS['meta'] = PMETA
METAKEYS['shift'] = 'lshift', 'rshift'

KEYS = dict([
    (ident[len('K_'):].lower(), getattr(pygame.locals, ident))
    for ident in dir(pygame.locals) if ident.startswith('K_')
])

KEYS['plus'] = ('=', '+', '.')
KEYS['quit'] = ('q', 'escape')
KEYS['help'] = ('h', '?', 'f1')

def GET_KEY(key):
    if len(key) == 1:
        return key
    return KEYS[key]

def permute_mods(base, args):
    if not args:
        yield base
        return
    first, rest = args[0], args[1:]
    for val in first:
        for rval in permute_mods(base | val, rest):
            yield rval

class Display(object):

    def __init__(self, (w,h)=(800,680)):
        pygame.init()
        self.resize((w,h))

    def resize(self, (w,h)):
        self.width = w
        self.height = h
        self.screen = pygame.display.set_mode((w, h), HWSURFACE|RESIZABLE, 32)


class GraphDisplay(Display):
    STATUSBARFONT = os.path.join(autopath.this_dir, 'VeraMoBd.ttf')
    ANIM_STEP = 0.07
    KEY_REPEAT = (500, 30)
    STATUSBAR_ALPHA = 0.75
    STATUSBAR_FGCOLOR = (255, 255, 80)
    STATUSBAR_BGCOLOR = (128, 0, 0)
    STATUSBAR_OVERFLOWCOLOR = (255, 0, 0)
    HELP_ALPHA = 0.95
    HELP_FGCOLOR = (255, 255, 80)
    HELP_BGCOLOR = (0, 128, 0)
    INPUT_ALPHA = 0.75
    INPUT_FGCOLOR = (255, 255, 80)
    INPUT_BGCOLOR = (0, 0, 128)

    KEYS = {
        'meta -' : ('zoom', 0.5),
             '-' : ('zoom', 0.5),
        'meta plus' : ('zoom', 2.0),
             'plus' : ('zoom', 2.0),
        'meta 0' : 'zoom_actual_size',
             '0' : 'zoom_actual_size',
        'meta 1' : 'zoom_to_fit',
             '1' : 'zoom_to_fit',
        'meta f4' : 'quit',
        'meta quit' : 'quit',
             'quit' : 'quit',
        'meta right' : 'layout_forward',
        'meta left': 'layout_back',
        'backspace' : 'layout_back',
        'f': 'search',
        '/': 'search',
        'n': 'find_next',
        'p': 'find_prev',
        'left' : ('pan', (-1, 0)),
        'right' : ('pan', (1, 0)),
        'up' : ('pan', (0, -1)),
        'down' : ('pan', (0, 1)),
        'shift left' : ('fast_pan', (-1, 0)),
        'shift right' : ('fast_pan', (1, 0)),
        'shift up' : ('fast_pan', (0, -1)),
        'shift down' : ('fast_pan', (0, 1)),
        'help': 'help',
    }

    HELP_MSG = """
    Key bindings:

        +, = or .       Zoom in
        -               Zoom out
        1               Zoom to fit
        0               Actual size

        Arrows          Scroll
        Shift+Arrows    Scroll faster

        Backspace       Go back in history
        Meta Left       Go back in history
        Meta Right      Go forward in history

        F or /          Search for text
        N               Find next occurrence
        P               Find previous occurrence

        F1, H or ?      This help message

        Q or Esc        Quit

    Mouse bindings:

        Click on objects to move around
        Drag with the left mouse button to zoom in/out
        Drag with the right mouse button to scroll
    """.replace('\n    ', '\n').strip()  # poor man's dedent


    def __init__(self, layout):
        super(GraphDisplay, self).__init__()
        self.font = pygame.font.Font(self.STATUSBARFONT, 16)
        self.viewers_history = []
        self.forward_viewers_history = []
        self.highlight_word = None
        self.highlight_obj = None
        self.viewer = None
        self.method_cache = {}
        self.key_cache = {}
        self.ascii_key_cache = {}
        self.status_bar_height = 0
        self.searchstr = None
        self.searchpos = 0
        self.searchresults = []
        self.initialize_keys()
        self.setlayout(layout)

    def initialize_keys(self):
        pygame.key.set_repeat(*self.KEY_REPEAT)
        for strnames, methodname in self.KEYS.iteritems():
            names = strnames.split()
            if not isinstance(methodname, basestring):
                methodname, args = methodname[0], methodname[1:]
            else:
                args = ()
            method = getattr(self, methodname, None)
            if method is None:
                print 'Can not implement key mapping %r, %s.%s does not exist' % (
                        strnames, self.__class__.__name__, methodname)
                continue

            mods = []
            basemod = 0
            keys = []
            for name in names:
                if name in METAKEYS:
                    val = METAKEYS[name]
                    if not isinstance(val, int):
                        mods.append(tuple([METAKEYS[k] for k in val]))
                    else:
                        basemod |= val
                else:
                    val = GET_KEY(name)
                    assert len(keys) == 0
                    if not isinstance(val, (int, basestring)):
                        keys.extend([GET_KEY(k) for k in val])
                    else:
                        keys.append(val)
            assert keys
            for key in keys:
                if isinstance(key, int):
                    for mod in permute_mods(basemod, mods):
                        self.key_cache[(key, mod)] = (method, args)
                else:
                    for mod in permute_mods(basemod, mods):
                        char = key.lower()
                        mod = mod & ~KMOD_SHIFT
                        self.ascii_key_cache[(char, mod)] = (method, args)

    def help(self):
        """Show a help window and wait for a key or a mouse press."""
        margin_x = margin_y = 64
        padding_x = padding_y = 8
        fgcolor = self.HELP_FGCOLOR
        bgcolor = self.HELP_BGCOLOR
        helpmsg = self.HELP_MSG
        width = self.width - 2*margin_x
        height = self.height - 2*margin_y
        lines = rendertext(helpmsg, self.font, fgcolor, width - 2*padding_x,
                           height - 2*padding_y)
        block = pygame.Surface((width, height), SWSURFACE | SRCALPHA)
        block.fill(bgcolor)
        sx = padding_x
        sy = padding_y
        for img in lines:
            w, h = img.get_size()
            block.blit(img, (sx, sy))
            sy += h
        block.set_alpha(int(255 * self.HELP_ALPHA))
        self.screen.blit(block, (margin_x, margin_y))

        pygame.display.flip()
        while True:
            e = pygame.event.wait()
            if e.type in (MOUSEBUTTONDOWN, KEYDOWN, QUIT):
                break
        self.must_redraw = True

    def input(self, prompt):
        """Ask the user to input something.

        Returns the string that the user entered, or None if the user pressed
        Esc.
        """

        def draw(text):
            margin_x = margin_y = 0
            padding_x = padding_y = 8
            fgcolor = self.INPUT_FGCOLOR
            bgcolor = self.INPUT_BGCOLOR
            width = self.width - 2*margin_x
            lines = renderline(text, self.font, fgcolor, width - 2*padding_x)
            height = totalheight(lines) + 2 * padding_y
            block = pygame.Surface((width, height), SWSURFACE | SRCALPHA)
            block.fill(bgcolor)
            sx = padding_x
            sy = padding_y
            for img in lines:
                w, h = img.get_size()
                block.blit(img, (sx, sy))
                sy += h
            block.set_alpha(int(255 * self.INPUT_ALPHA))
            # This can be slow.  It would be better to take a screenshot
            # and use it as the background.
            self.viewer.render()
            if self.statusbarinfo:
                self.drawstatusbar()
            self.screen.blit(block, (margin_x, margin_y))
            pygame.display.flip()

        draw(prompt)
        text = ""
        self.must_redraw = True
        while True:
            events = [pygame.event.wait()]
            events.extend(pygame.event.get())
            old_text = text
            for e in events:
                if e.type == QUIT:
                    return None
                elif e.type == KEYDOWN:
                    if e.key == K_ESCAPE:
                        return None
                    elif e.key == K_RETURN:
                        return text
                    elif e.key == K_BACKSPACE:
                        text = text[:-1]
                    elif e.unicode and ord(e.unicode) >= ord(' '):
                        text += e.unicode
            if text != old_text:
                draw(prompt + text)

    def search(self):
        searchstr = self.input('Find: ')
        if not searchstr:
            return
        self.searchstr = searchstr
        self.searchpos = -1
        self.searchresults = list(self.viewer.findall(self.searchstr))
        self.find_next()

    def find_next(self):
        if not self.searchstr:
            return
        if self.searchpos + 1 >= len(self.searchresults):
            self.setstatusbar('Not found: %s' % self.searchstr)
            return
        self.searchpos += 1
        self.highlight_found_item(self.searchresults[self.searchpos])

    def find_prev(self):
        if not self.searchstr:
            return
        if self.searchpos - 1 < 0:
            self.setstatusbar('Not found: %s' % self.searchstr)
            return
        self.searchpos -= 1
        self.highlight_found_item(self.searchresults[self.searchpos])

    def highlight_found_item(self, item):
        self.sethighlight(obj=item)
        if isinstance(item, Node):
            self.setstatusbar('Found node containing %s' % self.searchstr)
            self.look_at_node(item, keep_highlight=True)
        elif isinstance(item, Edge):
            self.setstatusbar('Found edge containing %s' % self.searchstr)
            self.look_at_edge(item, keep_highlight=True)
        else:
            # should never happen
            self.setstatusbar('Found %r containing %s' % (item, self.searchstr))

    def setlayout(self, layout):
        if self.viewer:
            self.viewers_history.append(self.viewer)
            del self.forward_viewers_history[:]
        self.layout = layout
        self.viewer = GraphRenderer(self.screen, layout)
        self.searchpos = 0
        self.searchresults = []
        self.zoom_to_fit()

    def zoom_actual_size(self):
        self.viewer.shiftscale(float(self.viewer.SCALEMAX) / self.viewer.scale)
        self.updated_viewer()

    def calculate_zoom_to_fit(self):
        return min(float(self.width) / self.viewer.width,
                float(self.height) / self.viewer.height,
                float(self.viewer.SCALEMAX) / self.viewer.scale)
    
    def zoom_to_fit(self):
        """
        center and scale to view the whole graph
        """

        f = self.calculate_zoom_to_fit()
        self.viewer.shiftscale(f)
        self.updated_viewer()

    def zoom(self, scale):
        self.viewer.shiftscale(max(scale, self.calculate_zoom_to_fit()))
        self.updated_viewer()

    def reoffset(self):
        self.viewer.reoffset(self.width, self.height)
    
    def pan(self, (x, y)):
        self.viewer.shiftoffset(x * (self.width // 8), y * (self.height // 8))
        self.updated_viewer()

    def fast_pan(self, (x, y)):
        self.pan((x * 4, y * 4))
    
    def update_status_bar(self):
        self.statusbarinfo = None
        self.must_redraw = True
        if self.viewers_history:
            info = 'Press Backspace to go back to previous screen'
        else:
            info = 'Press H for help'
        self.setstatusbar(info)
    
    def updated_viewer(self, keep_highlight=False):
        self.reoffset()
        if not keep_highlight:
            self.sethighlight()
            self.update_status_bar()
        self.must_redraw = True

    def layout_back(self):
        if self.viewers_history:
            self.forward_viewers_history.append(self.viewer)
            self.viewer = self.viewers_history.pop()
            self.layout = self.viewer.graphlayout
            self.updated_viewer()

    def layout_forward(self):
        if self.forward_viewers_history:
            self.viewers_history.append(self.viewer)
            self.viewer = self.forward_viewers_history.pop()
            self.layout = self.viewer.graphlayout
            self.updated_viewer()

    def setstatusbar(self, text, fgcolor=None, bgcolor=None):
        info = (text, fgcolor or self.STATUSBAR_FGCOLOR, bgcolor or self.STATUSBAR_BGCOLOR)
        if info != self.statusbarinfo:
            self.statusbarinfo = info
            self.must_redraw = True

    def drawstatusbar(self):
        text, fgcolor, bgcolor = self.statusbarinfo
        maxheight = self.height / 2
        lines = rendertext(text, self.font, fgcolor, self.width, maxheight,
                           self.STATUSBAR_OVERFLOWCOLOR)
        totalh = totalheight(lines)
        y = self.height - totalh
        self.status_bar_height = totalh + 16
        block = pygame.Surface((self.width, self.status_bar_height), SWSURFACE | SRCALPHA)
        block.fill(bgcolor)
        sy = 16
        for img in lines:
            w, h = img.get_size()
            block.blit(img, ((self.width-w)//2, sy-8))
            sy += h
        block.set_alpha(int(255 * self.STATUSBAR_ALPHA))
        self.screen.blit(block, (0, y-16))

    def notifymousepos(self, pos):
        word = self.viewer.at_position(pos)
        if word in self.layout.links:
            info = self.layout.links[word]
            self.setstatusbar(info)
            self.sethighlight(word)
            return
        node = self.viewer.node_at_position(pos)
        if node:
            self.setstatusbar(shortlabel(node.label))
            self.sethighlight(obj=node)
            return
        edge = self.viewer.edge_at_position(pos)
        if edge:
            info = '%s -> %s' % (shortlabel(edge.tail.label),
                                 shortlabel(edge.head.label))
            if edge.label:
                info += '\n' + shortlabel(edge.label)
            self.setstatusbar(info)
            self.sethighlight(obj=edge)
            return
        self.sethighlight()

    def notifyclick(self, pos):
        word = self.viewer.at_position(pos)
        if word in self.layout.links:
            newlayout = self.layout.followlink(word)
            if newlayout is not None:
                self.setlayout(newlayout)
                return
        node = self.viewer.node_at_position(pos)
        if node:
            self.look_at_node(node)
        else:
            edge = self.viewer.edge_at_position(pos)
            if edge:
                if (self.distance_to_node(edge.head) >=
                    self.distance_to_node(edge.tail)):
                    self.look_at_node(edge.head)
                else:
                    self.look_at_node(edge.tail)

    def sethighlight(self, word=None, obj=None):
        # The initialization of self.viewer.highlightwords should probably be
        # moved to setlayout()
        self.viewer.highlightwords = {}
        for name in self.layout.links:
            self.viewer.highlightwords[name] = ((128,0,0), None)
        if word:
            self.viewer.highlightwords[word] = ((255,255,80), (128,0,0))

        if word == self.highlight_obj and obj is self.highlight_obj:
            return # Nothing has changed, so there's no need to redraw

        if self.highlight_obj is not None:
            self.highlight_obj.sethighlight(False)
        if obj is not None:
            obj.sethighlight(True)
        self.highlight_word = word
        self.highlight_obj = obj
        self.must_redraw = True

    def animation(self, expectedtime=0.6):
        start = time.time()
        step = 0.0
        n = 0
        while True:
            step += self.ANIM_STEP
            if step >= expectedtime:
                break
            yield step / expectedtime
            n += 1
            now = time.time()
            frametime = (now-start) / n
            self.ANIM_STEP = self.ANIM_STEP * 0.9 + frametime * 0.1
        yield 1.0

    def distance_to_node(self, node):
        cx1, cy1 = self.viewer.getcenter()
        cx2, cy2 = node.x, node.y
        return (cx2-cx1)*(cx2-cx1) + (cy2-cy1)*(cy2-cy1)

    def look_at_node(self, node, keep_highlight=False):
        """Shift the node in view."""
        self.look_at(node.x, node.y, node.w, node.h, keep_highlight)

    def look_at_edge(self, edge, keep_highlight=False):
        """Shift the edge's label into view."""
        points = edge.bezierpoints()
        xmin = min([x for (x, y) in points])
        xmax = max([x for (x, y) in points])
        ymin = min([y for (x, y) in points])
        ymax = max([y for (x, y) in points])
        x = (xmin + xmax) / 2
        y = (ymin + ymax) / 2
        w = max(1, xmax - xmin)
        h = max(1, ymax - ymin)
        self.look_at(x, y, w, h, keep_highlight)

    def look_at(self, targetx, targety, targetw, targeth,
                     keep_highlight=False):
        """Shift the node in view."""
        endscale = min(float(self.width-40) / targetw,
                       float(self.height-40) / targeth,
                       75)
        startscale = self.viewer.scale
        cx1, cy1 = self.viewer.getcenter()
        cx2, cy2 = targetx, targety
        moving = (abs(startscale-endscale) + abs(cx1-cx2) + abs(cy1-cy2)
                  > 0.4)
        if moving:
            # if the target is far off the window, reduce scale along the way
            tx, ty = self.viewer.map(cx2, cy2)
            offview = max(-tx, -ty, tx-self.width, ty-self.height)
            middlescale = endscale * (0.999 ** offview)
            if offview > 150 and middlescale < startscale:
                bumpscale = 4.0 * (middlescale - 0.5*(startscale+endscale))
            else:
                bumpscale = 0.0
            if not keep_highlight:
                self.statusbarinfo = None
                self.sethighlight()
            for t in self.animation():
                self.viewer.setscale(startscale*(1-t) + endscale*t +
                                     bumpscale*t*(1-t))
                self.viewer.setcenter(cx1*(1-t) + cx2*t, cy1*(1-t) + cy2*t)
                self.updated_viewer(keep_highlight=keep_highlight)
                self.viewer.render()
                if self.statusbarinfo:
                    self.drawstatusbar()
                else:
                    self.status_bar_height = 0
                pygame.display.flip()
        return moving

    def peek(self, typ):
        for event in self.events:
            if event.type == typ:
                return True
        return False

    def process_event(self, event):
        method = self.method_cache.get(event.type, KeyError)
        if method is KeyError:
            method = getattr(self, 'process_%s' % (pygame.event.event_name(event.type),), None)
            self.method_cache[method] = method
        if method is not None:
            method(event)
        
    def process_MouseMotion(self, event):
        if self.peek(MOUSEMOTION):
            return
        if self.dragging:
            if (abs(event.pos[0] - self.click_origin[0]) +
                abs(event.pos[1] - self.click_origin[1])) > 12:
                self.click_time = None
            dx = event.pos[0] - self.dragging[0]
            dy = event.pos[1] - self.dragging[1]
            if event.buttons[0]:   # left mouse button
                self.zoom(1.003 ** (dx+dy))
            else:
                self.viewer.shiftoffset(-2*dx, -2*dy)
                self.updated_viewer()
            self.dragging = event.pos
            self.must_redraw = True
        else:
            self.notifymousepos(event.pos)

    def process_MouseButtonDown(self, event):
        self.dragging = self.click_origin = event.pos
        self.click_time = time.time()
        pygame.event.set_grab(True)

    def process_MouseButtonUp(self, event):
        self.dragging = None
        pygame.event.set_grab(False)
        if self.click_time is not None and abs(time.time() - self.click_time) < 1:
            # click (no significant dragging)
            self.notifyclick(self.click_origin)
        self.update_status_bar()
        self.click_time = None
        self.notifymousepos(event.pos)

    def process_KeyDown(self, event):
        method, args = self.key_cache.get((event.key, event.mod), (None, None))
        if method is None and event.unicode:
            char = event.unicode.lower()
            mod = event.mod & ~ KMOD_SHIFT
            method, args = self.ascii_key_cache.get((char, mod), (None, None))
        if method is not None:
            method(*args)

    def process_VideoResize(self, event):
        # short-circuit if there are more resize events pending
        if self.peek(VIDEORESIZE):
            return
        self.resize(event.size)
        self.must_redraw = True

    def process_Quit(self, event):
        self.quit()
     
    def async_quit(self):
        pygame.event.post(pygame.event.Event(QUIT))
    
    def quit(self):
        raise StopIteration
    
    def run(self):
        self.dragging = self.click_origin = self.click_time = None
        events = self.events = []
        try:

            while True:

                if self.must_redraw and not events:
                    self.viewer.render()
                    if self.statusbarinfo:
                        self.drawstatusbar()
                    else:
                        self.status_bar_height = 0
                    pygame.display.flip()
                    self.must_redraw = False

                if not events:
                    events.append(pygame.event.wait())
                    events.extend(pygame.event.get())

                self.process_event(events.pop(0))

        except StopIteration:
            pass

        # cannot safely close and re-open the display, depending on
        # Pygame version and platform.
        pygame.display.set_mode((self.width,1))


def shortlabel(label):
    """Shorten a graph node label."""
    return label.replace('\\l', '').splitlines()[0]


def renderline(text, font, fgcolor, width, maxheight=sys.maxint,
               overflowcolor=None):
    """Render a single line of text into a list of images.

    Performs word wrapping.
    """
    if overflowcolor is None:
        overflowcolor = fgcolor
    words = text.split(' ')
    lines = []
    while words:
        line = words.pop(0)
        img = font.render(line or ' ', 1, fgcolor)
        while words:
            longerline = line + ' ' + words[0]
            longerimg = font.render(longerline, 1, fgcolor)
            w, h = longerimg.get_size()
            if w > width:
                break
            words.pop(0)
            line = longerline
            img = longerimg
        w, h = img.get_size()
        if h > maxheight:
            img = font.render('...', 1, overflowcolor)
            w, h = img.get_size()
            while lines and h > maxheight:
                maxheight += lines.pop().get_size()[1]
            lines.append(img)
            break
        maxheight -= h
        lines.append(img)
    return lines


def rendertext(text, font, fgcolor, width, maxheight=sys.maxint,
               overflowcolor=None):
    """Render a multiline string into a list of images.

    Performs word wrapping for each line individually."""
    lines = []
    for line in text.splitlines():
        l = renderline(line, font, fgcolor, width, maxheight, overflowcolor)
        lines.extend(l)
        maxheight -= totalheight(l)
        if maxheight <= 0:
            break
    return lines


def totalheight(lines):
    """Calculate the total height of a list of images."""
    totalh = 0
    for img in lines:
        w, h = img.get_size()
        totalh += h
    return totalh
