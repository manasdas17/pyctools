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
``stats``      str  Show actual frame rate statistics. Can be ``'off'`` or ``'on'``.
=============  ===  ====

"""

__all__ = ['QtDisplay']
__docformat__ = 'restructuredtext en'

from collections import deque
import logging
import sys
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

    def __init__(self, widget, parent=None):
        super(BufferSwapper, self).__init__(parent)
        self.widget = widget

    @QtCore.pyqtSlot()
    def swap(self):
        self.widget.makeCurrent()
        self.widget.swapBuffers()
        now = time.time()
        self.widget.doneCurrent()
        self.done_swap.emit(now)


class SimpleDisplay(QtActorMixin, QtOpenGL.QGLWidget):
    do_swap = QtCore.pyqtSignal()

    def __init__(self, parent=None, flags=0):
        super(SimpleDisplay, self).__init__(parent, None, flags)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.in_queue = deque()
        self.image = None
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
        self._display_sync = True
        if display_freq > 500:
            self.logger.warning('Unable to synchronise to video frame rate')
            display_freq = 60
            self._display_sync = False
        self._display_period = 1.0 / float(display_freq)
        self._frame_period = 1.0 / 25.0
        self._show_stats = False
        self._scale = 1.0
        self._next_frame_due = 0.0
        self._swapping = False
        # create timer to show frames at regular intervals
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.display_frame)
        # create separate thread to swap buffers
        self.swapper_thread = QtCore.QThread()
        self.swapper = BufferSwapper(self)
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
        display_freq = int(0.5 + (5.0 / (time.time() - start)))
        print "frame freq: %d Hz" % (display_freq)
        self.doneCurrent()
        return display_freq

    def onStop(self):
        super(SimpleDisplay, self).onStop()
        self.timer.stop()
        self.swapper_thread.quit()
        self.swapper_thread.wait()
        self.close()

    def closeEvent(self, event):
        self.stop()

    @actor_method
    def set_framerate(self, framerate):
        self._frame_period = 1.0 / float(framerate)

    @actor_method
    def set_show_stats(self, show_stats):
        self._show_stats = show_stats

    @actor_method
    def set_scale(self, scale):
        self._scale = scale

    @actor_method
    def show_frame(self, frame, image):
        self.in_queue.append((frame, image))
        if self._swapping or len(self.in_queue) > 1:
            # no need to set timer
            return
        now = time.time()
        if not self._next_frame_due:
            # initialise
            self._next_frame_due = now
            self._display_clock = now
            self._frame_count = -2
        if self._next_frame_due > now + self._display_period:
            # set timer to show frame later
            sleep = self._next_frame_due - now
            print 'sleep A', sleep
            self.timer.start(int(sleep * 1000.0))
        else:
            # show frame immmediately
            self.display_frame()

    @QtCore.pyqtSlot(float)
    def done_swap(self, now):
        self._swapping = False
        self.timer.stop()
        margin = self._display_period / 2.0
        # adjust display clock
        while self._display_clock < now - margin:
            self._display_clock += self._display_period
        if self._display_sync:
            error = self._display_clock - now
            self._display_clock -= error / 100.0
            self._display_period -= error / 10000.0
        # adjust frame clock
        while self._next_frame_due < self._display_clock - margin:
            self._next_frame_due += self._display_period
        if self._display_sync:
            error = self._next_frame_due - self._display_clock
            while error > margin:
                error -= self._display_period
            if abs(error) < self._frame_period * self._display_period / 4.0:
                self._next_frame_due -= error
        if not self.in_queue:
            # nothing to do
            pass
        elif self._next_frame_due > self._display_clock + self._display_period:
            # set timer to show frame later
            sleep = self._next_frame_due - time.time()
##            print 'sleep B', sleep
            self.timer.start(int(sleep * 1000.0))
        else:
            # show frame immmediately
            self.display_frame()

    @QtCore.pyqtSlot()
    def display_frame(self):
        # display an image
        frame, self.image = self.in_queue.popleft()
        self._next_frame_due += self._frame_period
        self._frame_count += 1
        if self._frame_count <= 0:
            self._block_start = self._next_frame_due
        if self._next_frame_due - self._block_start > 5.0:
            if self._show_stats:
                frame_rate = float(self._frame_count) / (
                    self._next_frame_due - self._block_start)
                self.logger.warning('Average frame rate: %.2fHz', frame_rate)
            self._frame_count = 0
            self._block_start = self._next_frame_due
        h, w = frame.size()
        self.resize(w * self._scale, h * self._scale)
        if not self.isVisible():
            self.show()
        self.updateGL()
        self.doneCurrent()
        self._swapping = True
        self.do_swap.emit()

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

    def resizeGL(self, w, h):
        GL.glViewport(0, 0, w, h)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glOrtho(0, 1, 0, 1, -1, 1)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()

    def paintGL(self):
        if self.image is None:
            return
        ylen, xlen, bpc = self.image.shape
        if bpc == 3:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, xlen, ylen,
                            0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, self.image)
        elif bpc == 1:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, xlen, ylen,
                            0, GL.GL_LUMINANCE, GL.GL_UNSIGNED_BYTE, self.image)
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
        GL.glFlush()


class QtDisplay(Transformer):
    def initialise(self):
        self.config['shrink'] = ConfigInt(min_value=1, dynamic=True)
        self.config['expand'] = ConfigInt(min_value=1, dynamic=True)
        self.config['framerate'] = ConfigInt(min_value=1, value=25)
        self.config['stats'] = ConfigEnum(('off', 'on'))
        self.last_frame_type = None
        self.display = SimpleDisplay(None, Qt.Window | Qt.WindowStaysOnTopHint)

    def start(self):
        super(QtDisplay, self).start()
        self.display.start()

    def stop(self):
        super(QtDisplay, self).stop()
        self.display.stop()

    def join(self):
        super(QtDisplay, self).join()
        self.display.join()

    def process_start(self):
        super(QtDisplay, self).process_start()
        self.display.set_framerate(self.config['framerate'])
        self.display.set_show_stats(self.config['stats'] == 'on')

    def transform(self, in_frame, out_frame):
        if self.update_config():
            self.display.set_framerate(self.config['framerate'])
            self.display.set_show_stats(self.config['stats'] == 'on')
            shrink = self.config['shrink']
            expand = self.config['expand']
            self.display.set_scale(float(expand) / float(shrink))
        numpy_image = in_frame.as_numpy(dtype=numpy.uint8)
        if not numpy_image.flags.contiguous:
            numpy_image = numpy.ascontiguousarray(numpy_image)
        ylen, xlen, bpc = numpy_image.shape
        if bpc == 3:
            if in_frame.type != 'RGB' and in_frame.type != self.last_frame_type:
                self.logger.warning('Expected RGB input, got %s', in_frame.type)
        elif bpc == 1:
            if in_frame.type != 'Y' and in_frame.type != self.last_frame_type:
                self.logger.warning('Expected Y input, got %s', in_frame.type)
        else:
            self.logger.critical(
                'Cannot display %s frame with %d components', in_frame.type, bpc)
            return False
        self.last_frame_type = in_frame.type
        self.display.show_frame(in_frame, numpy_image)
        return True

def main():
    import logging
    from ..io.rawfilereader import RawFileReader
    from ..colourspace.yuvtorgb import YUVtoRGB
    from guild.actor import pipeline, start, stop, wait_for

    if len(sys.argv) != 2:
        print('usage: %s yuv_video_file' % sys.argv[0])
        return 1
    logging.basicConfig(level=logging.DEBUG)
    print('Qt display demonstration')
    QtGui.QApplication.setAttribute(Qt.AA_X11InitThreads)
    app = QtGui.QApplication([])
    source = RawFileReader()
    config = source.get_config()
    config['path'] = sys.argv[1]
    config['looping'] = 'reverse'
    source.set_config(config)
    conv = YUVtoRGB()
    sink = QtDisplay()
    pipeline(source, conv, sink)
    start(source, conv, sink)
    try:
        app.exec_()
    finally:
        stop(source, conv, sink)
        wait_for(source, conv, sink)
    return 0

if __name__ == '__main__':
    sys.exit(main())
