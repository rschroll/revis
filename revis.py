# Copyright 2011 Robert Schroll, rschroll@gmail.com
# http://rschroll.github.com/revis/
#
# This file is distributed under the terms of the BSD license, available
# at http://www.opensource.org/licenses/bsd-license.php

"""revis is an extension for Reinteract that embeds visvis figures in
worksheets.  Syntax:

    >>> with figure() as f:
    ...     <plotting command>
    ...      :
    ...     <plotting command>
    ...     f

where <plotting command> is any visvis command.  The single-command
plotting functions may be used without the with block.
"""
__version__ = "0.1"

import os, tempfile, threading
import cairo
import gobject
import gtk
import gtk.gtkgl # To keep from crashing on load.
from visvis.backends.backend_gtk import Figure, BaseFigure, GlCanvas, app
import visvis
if visvis.__version__.split('.') < ['1', '5']:
    print "Warning: visvis %s is not supported by revis.  Please upgrade to at least 1.5."%visvis.__version__

from threading import RLock
from reinteract.custom_result import CustomResult
from reinteract.statement import Statement
if hasattr(Statement, 'get_current'):
    _get_curr_statement = lambda: Statement.get_current()
else:
    _get_curr_statement = lambda: None

# From Stephen Langer (stephen.langer@nist.gov)
class IdleBlockCallback:
    def __init__(self, func, args=(), kwargs={}):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.event = threading.Event()
        self.result = None
    def __call__(self):
        #gtk.gdk.threads_enter()
        try:
            self.result = self.func(*self.args, **self.kwargs)
        finally:
            gtk.gdk.flush()
        #    gtk.gdk.threads_leave()
            self.event.set()
        return False              # don't repeat

def _run_in_main_loop(func, *args, **kwargs):
    if gobject.main_depth():
        # In the main loop already
        return func(*args, **kwargs)
    callbackobj = IdleBlockCallback(func, args, kwargs)
    callbackobj.event.clear()
    gobject.idle_add(callbackobj, priority=gobject.PRIORITY_LOW)
    callbackobj.event.wait()
    return callbackobj.result

maxcint = 65536.
def gdk2float(gdkcolor):
    return gdkcolor.red/maxcint, gdkcolor.green/maxcint, gdkcolor.blue/maxcint

class LightsWindow(gtk.Window):
    
    def __init__(self, figure, openbutton):
        gtk.Window.__init__(self) #, gtk.WINDOW_POPUP)
        self.set_resizable(False)
        self.set_title('Lights')
        self.figure = figure
        self.openbutton = openbutton
        
        table = gtk.Table(6, 4, True)
        self.chooser = gtk.combo_box_new_text()
        for i in range(8):
            self.chooser.append_text(str(i))
        self.chooser.connect("changed", self.on_choose_light)
        table.attach(self.chooser, 0,1, 0,1)
        
        for i, txt in enumerate(('position', 'ambient', 'diffuse', 'specular', 'color')):
            lab = gtk.Label(txt)
            lab.set_alignment(1, 0.5)
            table.attach(lab, 0,1, 1+i,2+i)
        self.cb_on = gtk.CheckButton('On')
        self.cb_on.connect("toggled", self.on_set_bool, "isOn")
        table.attach(self.cb_on, 1,2, 0,1)
        self.cb_cam = gtk.CheckButton('Camlight')
        self.cb_cam.connect("toggled", self.on_set_bool, "isCamLight")
        table.attach(self.cb_cam, 2,3, 0,1) # Should be able to do 2,4, but this messes up prev cb
        
        self.sb_pos = [gtk.SpinButton(gtk.Adjustment(0,-10,10,0.1,1), digits=1) for i in range(4)]
        hbox = gtk.HBox()
        for sb in self.sb_pos:
            sb.connect("value-changed", self.on_change_position)
            hbox.pack_start(sb)
        table.attach(hbox, 1,4, 1,2)
        
        self.sliders = [(val, gtk.HScale(gtk.Adjustment(0, 0, 1, 0.01, 0.1))) for val in ('ambient', 'diffuse', 'specular')]
        for i, (val, slider) in enumerate(self.sliders):
            slider.set_digits(2)
            slider.set_value_pos(gtk.POS_RIGHT)
            slider.connect("value-changed", self.on_change_intensity, val)
            table.attach(slider, 1,4, 2+i,3+i)
        
        box = gtk.HBox()
        self.color = gtk.ColorButton()
        self.color.connect("color-set", self.on_change_color)
        box.pack_start(self.color, False, False)
        table.attach(box, 1,4, 5,6)
        
        table.show_all()
        self.add(table)
        
        self.connect('delete-event', self.on_delete)
    
    def open(self):
        self.chooser.set_active(0)
        self.show()
    
    def on_delete(self, widget, event):
        self.openbutton.set_active(False)
        return True
    
    def on_choose_light(self, widget):
        self.currlight = None
        currlight = self.figure.currentAxes.lights[widget.get_active()]
        
        self.cb_on.set_active(currlight.isOn)
        self.cb_cam.set_active(currlight.isCamLight)
        for pos, sb in zip(currlight.position, self.sb_pos):
            sb.set_value(pos)
        for val, slider in self.sliders:
            cval = getattr(currlight, val)
            if isinstance(cval, tuple):
                print "Warning - destroying color of", val
                cval = (cval[0] + cval[1] + cval[2])/3.
            slider.set_value(cval)
        self.color.set_color(gtk.gdk.Color(*map(float, currlight.color[:3])))
        
        self.currlight = currlight
    
    def on_set_bool(self, widget, attr):
        if self.currlight is not None:
            if attr is "isOn":
                self.currlight.On(widget.get_active())
            else:
                setattr(self.currlight, attr, widget.get_active())
    
    def on_change_position(self, widget):
        if self.currlight is not None:
            self.currlight.position = [sb.get_value() for sb in self.sb_pos]
    
    def on_change_intensity(self, widget, attr):
        if self.currlight is not None:
            setattr(self.currlight, attr, widget.get_value())
    
    def on_change_color(self, widget):
        if self.currlight is not None:
            self.currlight.color = gdk2float(widget.get_color())

class Toolbar(gtk.Toolbar):
    
    def __init__(self, figure):
        gtk.Toolbar.__init__(self)
        self.figure = figure
        self.set_style(gtk.TOOLBAR_BOTH_HORIZ)
        
        savebutton = gtk.ToolButton(gtk.STOCK_SAVE_AS)
        savebutton.connect("clicked", self.savefig)
        self.insert(savebutton, 0)
        
        lightbutton = gtk.ToggleToolButton()
        lightbutton.set_icon_widget(gtk.Label('Lights'))
        lightbutton.set_label('Lights')
        lightbutton.connect("toggled", self.on_toggle_lights)
        self.insert(lightbutton, -1)
        
        self.lights_window = LightsWindow(self.figure, lightbutton)
        
        sep = gtk.SeparatorToolItem()
        sep.set_expand(True)
        sep.set_property('draw', False)
        self.insert(sep, -1)
        
        ti = gtk.ToolItem()
        self.view_lab = gtk.Label()
        self.view_lab.set_justify(gtk.JUSTIFY_RIGHT)
        ti.add(self.view_lab)
        self.insert(ti, -1)
        
        self.connect("destroy", self.on_destroy)
    
    def on_destroy(self, widget):
        self.lights_window.destroy()
        return False
    
    def savefig(self, widget):
        chooser = gtk.FileChooserDialog("Save As...", None, gtk.FILE_CHOOSER_ACTION_SAVE,
                                        (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                         gtk.STOCK_SAVE,   gtk.RESPONSE_OK))
        chooser.set_default_response(gtk.RESPONSE_OK)
        response = chooser.run()
        filename = None
        if response == gtk.RESPONSE_OK:
            filename = chooser.get_filename()
        chooser.destroy()
        
        if filename is not None:
            visvis.screenshot(filename, self.figure, sf=1)
    
    def update_view(self):
        view = self.figure.currentAxes.GetView()
        viewstr = ""
        isflycam = 1
        for k,v in sorted(view.items()):
            if k == 'azimuth':
                isflycam = 0
            if k == ('fov', 'rotation')[isflycam]:
                viewstr += '\n'
            viewstr += k + ': '
            if isinstance(v, tuple):
                viewstr += '(' + ','.join(['%0.3g'%vv for vv in v]) + ') '
            elif isinstance(v, visvis.Quaternion):
                viewstr += '%0.2g+%0.2gi+%0.2gj+%0.2gk '%(v.w, v.x, v.y, v.z)
            else:
                viewstr += '%0.3g '%v
        self.view_lab.set_text(viewstr)
    
    def on_toggle_lights(self, widget):
        if widget.get_active():
            pos = widget.allocation
            xo, yo = widget.window.get_origin()
            self.lights_window.move(xo + pos.x, yo + pos.y + pos.height)
            self.lights_window.set_transient_for(widget.get_toplevel())
            self.lights_window.open()
        else:
            self.lights_window.hide()


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
        _run_in_main_loop(Figure._ProcessGuiEvents, self)
    
    def _RedrawGui(self):
        Figure._RedrawGui(self)
        if hasattr(self, 'toolbar'):
            self.toolbar.update_view()

    
    def __enter__(self):
        self.__class__.lock.acquire()
        self.__class__.current_fig = self
        self._disable_reinteract_output()
        return self
    
    def __exit__(self, type, value, traceback):
        self.__class__.current_fig = None
        self._restore_reinteract_output()
        if self._widget is None:
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
    
    
    def _on_button_press(self, widget, event):
        # Grab the focus and return true to keep the event from bubbling up
        # to the TextView, which would grab focus right back.
        widget.grab_focus()
        return True
    
    def _on_key_press(self, widget, event):
        # Key presses are already handled in the GTK backend.  This just
        # keeps them from bubbling up to the TextView, which would insert
        # a character.
        return True
    
    def create_widget(self):
        app.Create()
        self._widget = GlCanvas(self)
        self._widget.set_size_request(*self._size)
        self._widget.connect("realize", lambda widget:
            widget.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.LEFT_PTR)))
        self._widget.connect("button_press_event", self._on_button_press)
        self._widget.connect("key_press_event", self._on_key_press)
        
        # We need a figure in order to get working glInfo
        if visvis.misc._glInfo[0] is None:
            self._widget.connect("realize", lambda widget: _getOpenGlInfo())
        
        self.toolbar = Toolbar(self)
        e = gtk.EventBox() # For setting cursor
        e.add(self.toolbar)
        self.toolbar.connect("realize", lambda widget:
            widget.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.LEFT_PTR)))
        
        box = gtk.VBox()
        box.pack_start(self._widget, True, True)
        box.pack_start(e, False, False)
        box.show_all()
        return box
    
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


# Make sure nothing calls getOpenGlInfo at a bad time.  Disable the old
# name and move the function to a new name, which we call at an appropriate
# place.
_getOpenGlInfo = visvis.misc.getOpenGlInfo
visvis.misc.getOpenGlInfo = lambda: tuple(visvis.misc._glInfo)

# Import visvis.functions to current namespace, for convenience
from visvis.functions import *

# Modify some of visvis's functions
_solo_funcs = ('bar3', 'grid', 'hist', 'imshow', 'movieShow', 'plot',
               'polarplot', 'surf', 'solidBox', 'solidCone',
               'solidCylinder', 'solidLine', 'solidRing', 'solidSphere',
               'solidTeapot', 'volshow')

_disable_funcs = ('close', 'closeAll', 'figure', 'ginput',
                  'processEvents', 'use')
_figure_doc = visvis.figure.__doc__

# Disable potentially harmful functions in visvis and current namespace.
# Don't worry about visvis.functions, though.
def _do_nothing(*args, **kw):
    """This function has been disabled by revis."""
    return None

for _cmd in _disable_funcs:
    setattr(visvis, _cmd, _do_nothing)
    exec('%s = _do_nothing'%_cmd)

# Change these functions, and push the changes back into visvis
def gcf():
    return SuperFigure.current_fig
gcf.__doc__ = visvis.gcf.__doc__
visvis.gcf = gcf
visvis.functions.gcf = gcf

def figure(*args, **kw):
    if args and isinstance(args[0], SuperFigure):
        return args[0]
    return SuperFigure(*args, **kw)
figure.__doc__ = _figure_doc
# Leave visvis.function nilpotent

def getframe(ob):
    fig = ob.GetFigure() # if ob is a figure, returns self.
    if fig._widget is not None:
        return _run_in_main_loop(visvis.functions.getframe, ob)
    else:
        raise RuntimeError, "Can't use getframe until the figure's widget has been created.\n" + \
                            "This error may have been triggered by a call of screenshot or record."
getframe.__doc__ = visvis.getframe.__doc__
visvis.getframe = getframe

def draw(figure=None, fast=False):
    # Replace figure.Draw() with figure.DrawNow(), as use here is to
    # update figure before screenshot and continuing on.
    if figure is None:
        figure = gcf()
    if figure is not None:
        figure.DrawNow(fast)
draw.__doc__ = visvis.draw.__doc__
visvis.draw = draw

# Allow 'solo' functions to be called outside of a with block
def _make_func(name):
    try:
        vfunc = getattr(visvis.functions, name)
    except AttributeError:
        return None
    
    def func(*args, **kw):
        SuperFigure.lock.acquire()
        try:
            if gcf() is None:
                with figure() as f:
                    vfunc(*args, **kw)
                if _get_curr_statement() is None:
                    return f
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

