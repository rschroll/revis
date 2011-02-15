"""revis allows embedding of visvis figures in Reinteract.
"""

import os, tempfile
import cairo
import gtk.gdk
import gtk.gtkgl # To keep from crashing on load.
from visvis.backends.backend_gtk import Figure, BaseFigure, GlCanvas, app
import visvis

from threading import RLock
from reinteract.custom_result import CustomResult
from reinteract.statement import Statement
if hasattr(Statement, 'get_current'):
    _get_curr_statement = lambda: Statement.get_current()
else:
    _get_curr_statement = lambda: None

class SuperFigure(Figure, CustomResult):
    
    lock = RLock()
    current_fig = None
    
    def __init__(self, disable_output=True, figsize=(560,420), **figkw):
        self._widget = None
        BaseFigure.__init__(self, **figkw) # Skip Figure, to avoid creating _widget
        self._disable_output = disable_output
        self._size = figsize
    
    def _GetPosition(self):
        # Sometimes this is called before the widget is made, so we have
        # to fake the answer
        if self._widget is not None:
            return Figure._GetPosition(self)
        else:
            return 0, 0, self._size[0], self._size[1]
    
    def _ProcessGuiEvents(self):
        # Disable this so it can't be called from non-mainloop thread.
        pass

    
    def __enter__(self):
        self.__class__.lock.acquire()
        self.__class__.current_fig = self
        self._disable_reinteract_output()
        return self
    
    def __exit__(self, type, value, traceback):
        self.__class__.current_fig = None
        self._restore_reinteract_output()
        self._output_figure()
        self.__class__.lock.release()
    
    def _disable_reinteract_output(self):
        self.statement = _get_curr_statement()
        if self.statement is not None:
            self.old_reinteract_output = self.statement.result_scope['reinteract_output']
            if self._disable_output:
                self.statement.result_scope['reinteract_output'] = lambda *args: None
    
    def _restore_reinteract_output(self):
        if self.statement is not None:
            self.statement.result_scope['reinteract_output'] = self.old_reinteract_output
    
    def _output_figure(self):
        if self.statement is not None:
            self.statement.result_scope['reinteract_output'](self)
    
    
    def create_widget(self):
        app.Create()
        self._widget = GlCanvas(self)
        self._widget.set_size_request(*self._size)
        self._widget.connect("realize", lambda widget:
            widget.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.LEFT_PTR)))
        return self._widget
    
    def print_result(self, context, render):
        cr = context.get_cairo_context()
        height = self._GetPosition()[-1]
        
        if render:
            sf = 2 # Scale factor for rendering.  (Note that screenshot
                   # doesn't actually do supersampling yet.)
            # PIL (used by screenshot) doesn't like pipes.
            fd, fn = tempfile.mkstemp()
            os.close(fd)
            visvis.screenshot(fn, self, sf=sf, format="png")
            image = cairo.ImageSurface.create_from_png(fn)
            os.unlink(fn)
            
            cr.scale(1./sf, 1./sf)
            cr.set_source_surface(image, 0, 0)
            cr.paint()
        
        return height

def gcf():
    return SuperFigure.current_fig
gcf.__doc__ = visvis.gcf.__doc__
visvis.gcf = gcf
visvis.functions.gcf = gcf

from visvis.functions import *

figure = lambda *args, **kw: SuperFigure(*args, **kw)
figure.__doc__ = visvis.figure.__doc__

_solo_funcs = ('bar3', 'grid', 'hist', 'imshow', 'movieShow', 'plot', 
               'polarplot', 'surf', 'solidBox', 'solidCone', 
               'solidCylinder', 'solidLine', 'solidRing', 'solidSphere',
               'solidTeapot', 'volshow')

_disable_funcs = ('close', 'closeAll', 'ginput', 'processEvents', 'use')

# Figure out what to do with these later....
_screenshot_funcs = ('draw', 'getframe', 'record', 'screenshot')

def _make_func(name):
    try:
        vfunc = getattr(visvis.functions, name)
    except AttributeError:
        return None
    
    def func(*args, **kw):
        SuperFigure.lock.acquire()
        try:
            if gcf() is None:
                with figure():
                    vfunc(*args, **kw)
            else:
                return vfunc(*args, **kw)
        finally:
            SuperFigure.lock.release()
    func.__doc__ = vfunc.__doc__
    return func

for _cmd in _solo_funcs:
    _func = _make_func(_cmd)
    if _func is not None:
        exec("%s = _func"%_cmd)

def _do_nothing(*args, **kw):
    """This function has been disabled by revis."""
    return None

for _cmd in _disable_funcs:
    exec("%s = _do_nothing"%_cmd)
