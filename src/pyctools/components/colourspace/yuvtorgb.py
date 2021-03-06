#!/usr/bin/env python
#  Pyctools - a picture processing algorithm development kit.
#  http://github.com/jim-easterbrook/pyctools
#  Copyright (C) 2014  Jim Easterbrook  jim@jim-easterbrook.me.uk
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

"""YUV (YCbCr) to RGB converter.

Convert "YUV" (actually YCbCr) frames (with any UV subsampling) to
RGB.

For ``4:2:2`` subsampling a high quality resampling filter is used, as
specified in `BBC R&D Report 1984/04
<http://www.bbc.co.uk/rd/publications/rdreport_1984_04>`_. For other
subsampling patterns, where the correct filtering is less well
specified, simple bicubic interpolation is used.

The ``matrix`` config item chooses the matrix coefficient set. It can
be ``'601'`` ("Rec 601", standard definition) or ``'709'`` ("Rec 709",
high definition). In ``'auto'`` mode the matrix is chosen according to
the number of lines in the image.

The ``range`` config item specifies the output video range. It can be
either ``'studio'`` (16..235) or ``'computer'`` (0..255). Values are
not clipped in either case.

"""

from __future__ import print_function

__all__ = ['YUVtoRGB']
__docformat__ = 'restructuredtext en'

import cv2
import numpy

from pyctools.core.config import ConfigEnum
from pyctools.core.base import Component
from pyctools.core.types import pt_float
from pyctools.components.interp.resize import resize_frame

class YUVtoRGB(Component):
    mat_601 = numpy.array([[1.0,  0.0,       1.37071],
                           [1.0, -0.336455, -0.698196],
                           [1.0,  1.73245,   0.0]], dtype=pt_float)
    mat_709 = numpy.array([[1.0,  0.0,       1.539648],
                           [1.0, -0.183143, -0.457675],
                           [1.0,  1.81418,   0.0]], dtype=pt_float)
    filter_21 = numpy.array([
        -0.002913300, 0.0,  0.010153700, 0.0, -0.022357799, 0.0,
         0.044929001, 0.0, -0.093861297, 0.0,  0.314049691, 0.5,
         0.314049691, 0.0, -0.093861297, 0.0,  0.044929001, 0.0,
        -0.022357799, 0.0,  0.010153700, 0.0, -0.002913300
        ], dtype=pt_float).reshape(1, -1, 1)
    inputs = ['input_Y', 'input_UV']
    with_outframe_pool = True

    def initialise(self):
        self.config['matrix'] = ConfigEnum(('auto', '601', '709'), dynamic=True)
        self.config['range'] = ConfigEnum(('studio', 'computer'), dynamic=True)
        self.last_frame_type = None

    def process_frame(self):
        Y_frame = self.input_buffer['input_Y'].get()
        UV_frame = self.input_buffer['input_UV'].get()
        out_frame = self.outframe_pool['output'].get()
        out_frame.initialise(Y_frame)
        if self.transform(Y_frame, UV_frame, out_frame):
            self.output(out_frame)
        else:
            self.output(None)
            self.stop()
            return

    def transform(self, Y_frame, UV_frame, out_frame):
        self.update_config()
        # check input and get data
        Y_data = Y_frame.as_numpy()
        if Y_data.shape[2] != 1:
            self.logger.critical('Y input has %d components', Y_data.shape[2])
            return False
        UV_data = UV_frame.as_numpy()
        if UV_data.shape[2] != 2:
            self.logger.critical('UV input has %d components', UV_data.shape[2])
            return False
        audit = 'Y = {\n%s}\n' % Y_frame.metadata.get('audit')
        audit += 'UV = {\n%s}\n' % UV_frame.metadata.get('audit')
        audit += 'data = YUVtoRGB(Y, UV)\n'
        # apply offset
        Y_data = Y_data - pt_float(16.0)
        # resample U & V
        v_ss = Y_data.shape[0] // UV_data.shape[0]
        h_ss = Y_data.shape[1] // UV_data.shape[1]
        if h_ss == 2:
            UV_data = resize_frame(UV_data, self.filter_21, 2, 1, 1, 1)
        elif h_ss != 1:
            UV_data = cv2.resize(
                UV_data, None, fx=h_ss, fy=1, interpolation=cv2.INTER_CUBIC)
        if v_ss != 1:
            UV_data = cv2.resize(
                UV_data, None, fx=1, fy=v_ss, interpolation=cv2.INTER_CUBIC)
        # matrix to RGB
        audit += '    range: %s' % (self.config['range'])
        if (self.config['matrix'] == '601' or
                (self.config['matrix'] == 'auto' and Y_data.shape[0] <= 576)):
            matrix = self.mat_601
            audit += ', matrix: 601\n'
        else:
            matrix = self.mat_709
            audit += ', matrix: 709\n'
        YUV = numpy.dstack((Y_data, UV_data))
        RGB = numpy.dot(YUV, matrix.T)
        # offset or scale
        if self.config['range'] == 'studio':
            RGB += pt_float(16.0)
        else:
            RGB *= pt_float(255.0 / 219.0)
        out_frame.data = RGB
        out_frame.type = 'RGB'
        out_frame.metadata.set('audit', audit)
        return True
