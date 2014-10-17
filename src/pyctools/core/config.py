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

"""Configuration classes.

Provides configuration via a tree of different node types for
different value types.

"""

import copy
import sys

class ConfigLeafNode(object):
    def __init__(self, value=None, dynamic=False):
        self.value = value
        self.dynamic = dynamic

    def get(self):
        return self.value

    def set(self, value):
        if not self.validate(value):
            raise ValueError(str(value))
        self.value = value

    def __repr__(self):
        return repr(self.value)

class ConfigPath(ConfigLeafNode):
    def validate(self, value):
        return isinstance(value, str)

class ConfigInt(ConfigLeafNode):
    def __init__(self, value=None, dynamic=False,
                 min_value=-sys.maxint, max_value=sys.maxint):
        super(ConfigInt, self).__init__(value, dynamic)
        self.min_value = min_value
        self.max_value = max_value
        if value is None:
            self.value = min(max(0, self.min_value), self.max_value)

    def validate(self, value):
        return (isinstance(value, int) and
                value >= self.min_value and value <= self.max_value)

class ConfigFloat(ConfigLeafNode):
    def __init__(self, value=None, dynamic=False,
                 min_value=-sys.float_info.max, max_value=sys.float_info.max,
                 decimals=8, wrapping=False):
        super(ConfigFloat, self).__init__(value, dynamic)
        self.min_value = min_value
        self.max_value = max_value
        self.decimals = decimals
        self.wrapping = wrapping
        if value is None:
            self.value = min(max(0.0, self.min_value), self.max_value)

    def validate(self, value):
        return (isinstance(value, float) and
                value >= self.min_value and value <= self.max_value)

class ConfigStr(ConfigLeafNode):
    def validate(self, value):
        return isinstance(value, str)

class ConfigEnum(ConfigLeafNode):
    def __init__(self, choices, **kw):
        super(ConfigEnum, self).__init__(value=choices[0], **kw)
        self.choices = choices

    def validate(self, value):
        return value in self.choices

class ConfigParent(ConfigLeafNode):
    def __init__(self):
        super(ConfigParent, self).__init__(value={})

    def validate(self, value):
        return isinstance(value, dict)

    def __getitem__(self, key):
        return self.value[key].get()

    def __setitem__(self, key, value):
        if key in self.value:
            self.value[key].set(value)
        else:
            self.value[key] = value

class ConfigGrandParent(ConfigParent):
    def __getitem__(self, key):
        return self.value[key]

    def __setitem__(self, key, value):
        self.value[key] = value

class ConfigMixin(object):
    def __init__(self):
        self.config = ConfigParent()

    def get_config(self):
        # make copy to allow changes without affecting running
        # component
        return copy.deepcopy(self.config)

    def set_config(self, config):
        # single object assignment should be thread-safe, so can
        # update running component
        self.config = copy.deepcopy(config)
