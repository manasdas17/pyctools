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

"""Component configuration classes.

The :py:class:`ConfigMixin` mixin class can be used with any component
to provide a hierarchical tree of named configuration values. Each
configuration value node has a fixed type and can be configured to
have constraints such as maximum and minimum values.

Configuration values are accessed in a dictionary-like manner. During
a component's initialisation you should create the required
configuration nodes like this::

    self.config['zlen'] = ConfigInt(value=100, min_value=1)
    self.config['looping'] = ConfigEnum(('off', 'repeat'))

Subsequently the config object behaves more like a dictionary::

    self.config['zlen'] = 250
    ...
    zlen = self.config['zlen']

Users of a component can initialise its configuration by passing
key-value pairs to the component's constructor::

    resize = Resize(xup=xup, xdown=xdown)

The configuration can be changed, even when the component is running,
with the :py:meth:`~ConfigMixin.get_config` and
:py:meth:`~ConfigMixin.set_config` methods::

    cfg = resize.get_config()
    cfg['xup'] = 3
    cfg['xdown'] = 4
    resize.set_config(cfg)

Note that these methods are thread-safe and make a copy of the
configuration tree. This ensures that all your configuration changes
are applied together, some time after calling
:py:meth:`~ConfigMixin.set_config`.

.. autosummary::
   :nosignatures:

   ConfigMixin
   ConfigParent
   ConfigGrandParent
   ConfigInt
   ConfigFloat
   ConfigStr
   ConfigPath
   ConfigEnum
   ConfigLeafNode

"""

__docformat__ = 'restructuredtext en'

import collections
import copy

class ConfigLeafNode(object):
    """Base class for configuration nodes.

    :keyword object value: Initial value of the node.

    :keyword bool dynamic: Whether the value can be changed while the
        component is running. Not currently used anywhere.

    :keyword object min_value: Minimum value of the node, for types
        where it's relevant.

    :keyword object max_value: Maximum value of the node, for types
        where it's relevant.

    """
    def __init__(self, value=None, dynamic=False, min_value=None, max_value=None):
        self.value = value
        self.dynamic = dynamic
        self.min_value = min_value
        self.max_value = max_value
        self.default = value

    def parser_add(self, parser, key):
        parser.add_argument('--' + key, default=self.value, **self.parser_kw)

    def get(self):
        """Return the config item's current value."""
        return self.value

    def set(self, value):
        """Set the config item's value."""
        if not self.validate(value):
            raise ValueError(str(value))
        self.value = value

    def clip(self, value):
        """Return a limited value, for types that have maximum or
        minimum values.

        This method does not affect the config item's current value.

        """
        if self.max_value is not None:
            value = min(value, self.max_value)
        if self.min_value is not None:
            value = max(value, self.min_value)
        return value

    def __repr__(self):
        return repr(self.value)


class ConfigPath(ConfigLeafNode):
    """File pathname configuration node.

    """
    parser_kw = {'metavar' : 'path'}

    def validate(self, value):
        return isinstance(value, str)


class ConfigInt(ConfigLeafNode):
    """Integer configuration node.

    """
    parser_kw = {'type' : int, 'metavar' : 'n'}

    def __init__(self, **kw):
        super(ConfigInt, self).__init__(**kw)
        if self.value is None:
            self.value = self.clip(0)
            self.default = self.value

    def validate(self, value):
        return isinstance(value, int) and self.clip(value) == value


class ConfigFloat(ConfigLeafNode):
    """Float configuration node.

    :keyword int decimals: How many decimal places to use when
        displaying the value.

    :keyword bool wrapping: Should the value change to min_value when
        incremented beyond max_value or *vice versa*.

    """
    parser_kw = {'type' : float, 'metavar' : 'x'}

    def __init__(self, decimals=8, wrapping=False, **kw):
        super(ConfigFloat, self).__init__(**kw)
        self.decimals = decimals
        self.wrapping = wrapping
        if self.value is None:
            self.value = self.clip(0.0)
            self.default = self.value

    def validate(self, value):
        return isinstance(value, float) and self.clip(value) == value


class ConfigStr(ConfigLeafNode):
    """String configuration node.

    """
    parser_kw = {'metavar' : 'str'}

    def validate(self, value):
        return isinstance(value, str)


class ConfigEnum(ConfigLeafNode):
    """'Enum' configuration node.

    The value can be one of a list of choices.

    :keyword list choices: a list of strings that are the possible
        values of the config item. Initial value is the first in the
        list.

    :keyword bool extendable: can the choices list be extended by
        setting new values.

    """
    def __init__(self, choices, extendable=False, **kw):
        super(ConfigEnum, self).__init__(value=choices[0], **kw)
        self.choices = list(choices)
        self.extendable = extendable
        self.parser_kw = {'metavar' : 'str'}
        if not self.extendable:
            self.parser_kw['choices'] = self.choices

    def validate(self, value):
        if self.extendable and value not in self.choices:
            self.choices.append(value)
        return value in self.choices


class ConfigParent(ConfigLeafNode):
    """Parent configuration node.

    Stores a set of child nodes in a :py:class:`dict`.

    """
    def __init__(self):
        super(ConfigParent, self).__init__(value={})

    def validate(self, value):
        return isinstance(value, dict)

    def parser_add(self, parser, prefix=''):
        if prefix:
            prefix += '.'
        for key, value in self.value.items():
            value.parser_add(parser, prefix + key)

    def parser_set(self, args):
        for key, value in vars(args).items():
            parts = key.split('.')
            while len(parts) > 1:
                value = {parts[-1] : value}
                del parts[-1]
            key = parts[0]
            self.value[key].set(value)

    def set(self, value):
        """Set the config item's value."""
        if not self.validate(value):
            raise ValueError(str(value))
        for k, v in value.items():
            self.value[k].set(v)

    def __repr__(self):
        result = {}
        for key, value in self.value.items():
            if value.value != value.default:
                result[key] = value
        return repr(result)

    def __getitem__(self, key):
        return self.value[key].get()

    def __setitem__(self, key, value):
        if isinstance(value, ConfigLeafNode):
            self.value[key] = value
        else:
            self.value[key].set(value)


class ConfigGrandParent(ConfigParent):
    """Grandparent configuration node.

    Stores a set of :py:class:`ConfigParent` nodes in a
    :py:class:`dict`.

    """
    pass


class ConfigMixin(object):
    """Add a config tree to a pyctools component.

    """
    def __init__(self):
        self.config = ConfigParent()
        self._configmixin_queue = collections.deque()

    def get_config(self):
        """Get a copy of the component's current configuration.

        Using a copy allows the config to be updated in a threadsafe
        manner while the component is running. Use the
        :py:meth:`set_config` method to update the component's
        configuration after making changes to the copy.

        :return: Copy of component's configuration.

        :rtype: :py:class:`ConfigParent`

        """
        # get any queued changes
        self.update_config()
        # make copy to allow changes without affecting running
        # component
        return copy.deepcopy(self.config)

    def set_config(self, config):
        """Update the component's configuration.

        Use the :py:meth:`get_config` method to get a copy of the
        component's configuration, update that copy then call
        :py:meth:`set_config` to update the component. This enables
        the configuration to be changed in a threadsafe manner while
        the component is running, and allows several values to be
        changed at once.

        :param ConfigParent config: New configuration.

        """
        # put copy of config on queue for running component
        self._configmixin_queue.append(copy.deepcopy(config))

    def update_config(self):
        """Pull any changes made with :py:meth:`set_config`.

        Call this from within your component before using any config
        values to ensure you have the latest values set by the user.

        :return: Whether the config was updated.
        :rtype: bool

        """
        result = False
        while self._configmixin_queue:
            self.config = self._configmixin_queue.popleft()
            result = True
        return result
