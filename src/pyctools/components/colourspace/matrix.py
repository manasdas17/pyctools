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

"""Matrix any number of components.

"""

__all__ = ['Matrix']

from guild.actor import *
import numpy

from pyctools.core import Transformer

class Matrix(Transformer):
    inputs = ['input', 'matrix']

    def initialise(self):
        self.ready = False

    @actor_method
    def matrix(self, new_matrix):
        if not isinstance(new_matrix, numpy.ndarray):
            self.logger.warning('Matrix input must be a numpy array')
            return
        if new_matrix.ndim != 2:
            self.logger.warning('Matrix input must be 2 dimensional')
            return
        self.matrix_coefs = new_matrix
        self.ready = True

    def transform(self, in_frame, out_frame):
        data_in = in_frame.as_numpy(dtype=numpy.float32, dstack=True)[0]
        if data_in.shape[2] != self.matrix_coefs.shape[1]:
            self.logger.critical('Input has %d components, matrix expects %d',
                                 data_in.shape[2], self.matrix_coefs.shape[1])
            return False
        out_frame.data = [numpy.dot(data_in, self.matrix_coefs.T)]
        return True