#!/usr/bin/env python
#  Pyctools - a picture processing algorithm development kit.
#  http://github.com/jim-easterbrook/pyctools
#  Copyright (C) 2014-15  Jim Easterbrook  jim@jim-easterbrook.me.uk
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see
#  <http://www.gnu.org/licenses/>.

"""Display images in a Qt window.

This is a "pass through" component that can be inserted anywhere in a
pipeline to display the images at that point.

The displayed image can be enlarged or reduced in size by setting the
``expand`` and ``shrink`` config values. The size changing is done
within OpenGL.

The ``framerate`` config item sets a target rate (default value 25
fps). If the incoming video cannot keep up then frames will be
repeated. Otherwise the entire processing pipeline is slowed down to
supply images at the correct rate.

=============  ===  ====
Config
=============  ===  ====
``expand``     int  Image up-conversion factor.
``shrink``     int  Image down-conversion factor.
``framerate``  int  Target frame rate.
``repeat``     str  Repeat frames until next one arrives. Can be ``'off'`` or ``'on'``.
``sync``       str  Synchronise to video card frame rate. Can be ``'off'`` or ``'on'``.
``stats``      str  Show actual frame rate statistics. Can be ``'off'`` or ``'on'``.
=============  ===  ====

"""

__all__ = ['QtDisplay']
__docformat__ = 'restructuredtext en'

from collections import deque
import threading
import time

from guild.actor import actor_method
from guild.qtactor import QtActorMixin
import numpy
from OpenGL import GL
from PyQt4 import QtGui, QtCore, QtOpenGL
from PyQt4.QtCore import Qt

from pyctools.core.config import ConfigInt, ConfigEnum
from pyctools.core.base import Transformer

class BufferSwapper(QtCore.QObject):
    done_swap = QtCore.pyqtSignal(float)

    def __init__(self, widget, ctx_lock, parent=None):
        super(BufferSwapper, self).__init__(parent)
        self.widget = widget
        self.ctx_lock = ctx_lock

    @QtCore.pyqtSlot()
    def swap(self):
        self.ctx_lock.acquire()
        self.widget.makeCurrent()
        self.widget.swapBuffers()
        now = time.time()
        self.widget.doneCurrent()
        self.ctx_lock.release()
        self.done_swap.emit(now)


class SimpleDisplay(QtActorMixin, QtOpenGL.QGLWidget):
    do_swap = QtCore.pyqtSignal()

    def __init__(self, owner, parent=None, flags=0):
        super(SimpleDisplay, self).__init__(parent, None, flags)
        self.owner = owner
        self.in_queue = deque()
        self.numpy_image = None
        self.setAutoBufferSwap(False)
        # if user has set "tear free video" or similar, we might not
        # want to increase swap interval any further
        fmt = self.format()
        fmt.setSwapInterval(0)
        self.setFormat(fmt)
        display_freq = self.measure_display_rate()
        if display_freq > 500:
            # unfeasibly fast => not synchronised
            fmt.setSwapInterval(1)
            self.setFormat(fmt)
            display_freq = self.measure_display_rate()
            self.sync_swap_interval = 1
        else:
            self.sync_swap_interval = 0
        if display_freq > 500:
            self.owner.logger.warning('Unable to synchronise to video frame rate')
            display_freq = 60
            self.sync_swap_interval = -1
        self.sync_swap = self.sync_swap_interval >= 0
        self._display_period = 1.0 / float(display_freq)
        self._frame_period = 1.0 / 25.0
        self._next_frame_due = 0.0
        self.last_frame_type = None
        self.scale = -1.0
        # create separate thread to swap buffers
        self.ctx_lock = threading.RLock()
        self.swapper_thread = QtCore.QThread()
        self.swapper = BufferSwapper(self, self.ctx_lock)
        self.swapper.moveToThread(self.swapper_thread)
        self.do_swap.connect(self.swapper.swap)
        self.swapper.done_swap.connect(self.done_swap)
        self.swapper_thread.start()

    def measure_display_rate(self):
        self.makeCurrent()
        self.swapBuffers()
        start = time.time()
        for n in range(5):
            self.swapBuffers()
        self.doneCurrent()
        display_freq = int(0.5 + (5.0 / (time.time() - start)))
        self.owner.logger.info('Display frequency: %dHz', display_freq)
        return display_freq

    def onStop(self):
        super(SimpleDisplay, self).onStop()
        self.swapper.blockSignals(True)
        self.swapper_thread.quit()
        self.swapper_thread.wait()
        self.close()

    def closeEvent(self, event):
        self.stop()

    @actor_method
    def show_frame(self, frame):
        self.in_queue.append(frame)
        first_time = not self._next_frame_due
        # get latest config
        if first_time or self.owner.update_config():
            scale = (float(self.owner.config['expand']) /
                     float(self.owner.config['shrink']))
            if self.scale != scale:
                self.scale = scale
                h, w = frame.size()
                self.resize(w * scale, h * scale)
            self._frame_period = 1.0 / float(self.owner.config['framerate'])
            self.show_stats = self.owner.config['stats'] == 'on'
            self._repeat = self.owner.config['repeat'] == 'on'
            sync = (self.sync_swap_interval >= 0 and
                    self.owner.config['sync'] == 'on')
            if self.sync_swap != sync:
                self.sync_swap = sync
                if self.sync_swap_interval > 0:
                    self.ctx_lock.acquire()
                    self.makeCurrent()
                    fmt = self.format()
                    if self.sync_swap:
                        fmt.setSwapInterval(self.sync_swap_interval)
                    else:
                        fmt.setSwapInterval(0)
                    self.setFormat(fmt)
                    self.ctx_lock.release()
        if first_time:
            # initialise
            self.makeCurrent()
            self.swapBuffers()
            self.swapBuffers()
            now = time.time()
            self._next_frame_due = now
            self._display_clock = now
            self._frame_count = -2
            self.done_swap(now)
            self.show()

    @QtCore.pyqtSlot(float)
    def done_swap(self, now):
        margin = self._display_period / 2.0
        # adjust display clock
        while self._display_clock < now - margin:
            self._display_clock += self._display_period
        if self.sync_swap:
            error = self._display_clock - now
            self._display_clock -= error / 100.0
            self._display_period -= error / 10000.0
        # adjust frame clock
        while self._next_frame_due < self._display_clock - margin:
            self._next_frame_due += self._display_period
        if self.sync_swap:
            error = self._next_frame_due - self._display_clock
            while error > margin:
                error -= self._display_period
            if abs(error) < self._frame_period * self._display_period / 4.0:
                self._next_frame_due -= error
        next_slot = self._display_clock + self._display_period
        if self.in_queue and self._next_frame_due <= next_slot + margin:
            # show frame immmediately
            self.next_frame()
        elif not self._repeat:
            # show blank frame immediately
            self.numpy_image = numpy.zeros((1, 1, 1), dtype=numpy.uint8)
        # refresh displayed image
        self.updateGL()
        self.doneCurrent()
        self.do_swap.emit()

    def next_frame(self):
        in_frame = self.in_queue.popleft()
        self.numpy_image = in_frame.as_numpy(dtype=numpy.uint8)
        if not self.numpy_image.flags.contiguous:
            self.numpy_image = numpy.ascontiguousarray(self.numpy_image)
        bpc = self.numpy_image.shape[2]
        if bpc == 3:
            if in_frame.type != 'RGB' and in_frame.type != self.last_frame_type:
                self.owner.logger.warning(
                    'Expected RGB input, got %s', in_frame.type)
        elif bpc == 1:
            if in_frame.type != 'Y' and in_frame.type != self.last_frame_type:
                self.owner.logger.warning(
                    'Expected Y input, got %s', in_frame.type)
        else:
            self.owner.logger.critical(
                'Cannot display %s frame with %d components', in_frame.type, bpc)
            self.owner.stop()
            self.numpy_image = None
            return
        self.last_frame_type = in_frame.type
        self._next_frame_due += self._frame_period
        self._frame_count += 1
        if self._frame_count <= 0:
            self._block_start = self._next_frame_due
        if self._next_frame_due - self._block_start > 5.0:
            if self.show_stats:
                frame_rate = float(self._frame_count) / (
                    self._next_frame_due - self._block_start)
                self.owner.logger.warning(
                    'Average frame rate: %.2fHz', frame_rate)
            self._frame_count = 0
            self._block_start = self._next_frame_due

    def glInit(self):
        self.ctx_lock.acquire()
        super(SimpleDisplay, self).glInit()
        self.ctx_lock.release()

    def initializeGL(self):
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_TEXTURE_2D)
        texture = GL.glGenTextures(1)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
        GL.glTexParameterf(
            GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameterf(
            GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)

    def resizeEvent(self, event):
        self.ctx_lock.acquire()
        super(SimpleDisplay, self).resizeEvent(event)
        self.ctx_lock.release()

    def resizeGL(self, w, h):
        GL.glViewport(0, 0, w, h)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glOrtho(0, 1, 0, 1, -1, 1)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()

    def paintEvent(self, event):
        # ignore paint events as widget is redrawn every frame period anyway
        return

    def glDraw(self):
        self.ctx_lock.acquire()
        super(SimpleDisplay, self).glDraw()
        self.ctx_lock.release()

    def paintGL(self):
        if self.numpy_image is None:
            return
        ylen, xlen, bpc = self.numpy_image.shape
        if bpc == 3:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, xlen, ylen,
                            0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, self.numpy_image)
        elif bpc == 1:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, xlen, ylen,
                            0, GL.GL_LUMINANCE, GL.GL_UNSIGNED_BYTE, self.numpy_image)
        else:
            return
        GL.glBegin(GL.GL_QUADS)
        GL.glTexCoord2i(0, 0)
        GL.glVertex2i(0, 1)
        GL.glTexCoord2i(0, 1)
        GL.glVertex2i(0, 0)
        GL.glTexCoord2i(1, 1)
        GL.glVertex2i(1, 0)
        GL.glTexCoord2i(1, 0)
        GL.glVertex2i(1, 1)
        GL.glEnd()


class QtDisplay(Transformer):
    def initialise(self):
        self.config['shrink'] = ConfigInt(min_value=1, dynamic=True)
        self.config['expand'] = ConfigInt(min_value=1, dynamic=True)
        self.config['framerate'] = ConfigInt(min_value=1, value=25)
        self.config['sync'] = ConfigEnum(('off', 'on'))
        self.config['sync'] = 'on'
        self.config['repeat'] = ConfigEnum(('off', 'on'))
        self.config['repeat'] = 'on'
        self.config['stats'] = ConfigEnum(('off', 'on'))
        self.display = SimpleDisplay(
            self, None, Qt.Window | Qt.WindowStaysOnTopHint)

    def start(self):
        super(QtDisplay, self).start()
        self.display.start()

    def stop(self):
        super(QtDisplay, self).stop()
        self.display.stop()

    def join(self):
        super(QtDisplay, self).join()
        self.display.join()

    def transform(self, in_frame, out_frame):
        self.display.show_frame(in_frame)
        return True
