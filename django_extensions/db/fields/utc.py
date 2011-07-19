# -*- coding: utf-8 -*-
# http://djangosnippets.org/snippets/388/
# depends on pytz

import datetime
import warnings
import pytz
from django.conf import settings
from django.db import models
from django.dispatch import dispatcher
from django.db.models import signals

try:
    pytz_exc = (pytz.UnknownTimeZoneError,)
except AttributeError:
    # older versions of pytz
    pytz_exc = (IOError, KeyError)

TIMEZONES = tuple((t, t) for t in pytz.all_timezones)


class UTCDateTimeField(models.DateTimeField):

    def __init__(self, *args, **kw):
        self.default_tz = kw.get('default_tz')
        if 'default_tz' in kw:
            del(kw['default_tz'])
        super(UTCDateTimeField, self).__init__(*args, **kw)
        self._name = None

    def get_internal_type(self):
        return 'DateTimeField'

    def _model_init(self, signal, sender, instance, **kw):
        setattr(instance, "_%s" % self._name, getattr(instance, self._name))
        setattr(instance, "_%s_utc" % self._name, getattr(instance, "%s_utc" % self._name))
        setattr(instance, "_%s_tz" % self._name, getattr(instance, "%s_tz" % self._name))

    def _model_pre_save(self, signal, sender, instance, **kw):
        dt = getattr(instance, self._name)
        utc = getattr(instance, "%s_utc" % self._name)
        tz = getattr(instance, "%s_tz" % self._name)
        if not tz:
            # try to get the default
            if isinstance(self.default_tz, basestring):
                tz = getattr(instance, self.default_tz)
                if isinstance(tz, basestring):
                    # use it as a timezone
                    pass
                elif callable(tz):
                    self.default_tz = tz
                    tz = None
                else:
                    warnings.warn("UTCDateTimeField cannot use default_tz %s in model %s" % (self.default_tz, instance))
                    self.default_tz = lambda: getattr(settings, 'TIME_ZONE', 'UTC')
                    tz = None
            if callable(self.default_tz):
                tz = self.default_tz()
                if not tz or not isinstance(tz, basestring):
                    warnings.warn("UTCDateTimeField cannot use default timezone %s, using Django default" % tz)
                    tz = getattr(settings, 'TIME_ZONE', 'UTC')
            if not tz:
                tz = getattr(settings, 'TIME_ZONE', 'UTC')
            setattr(instance, "%s_tz" % self._name, tz)
        _dt = getattr(instance, "_%s" % self._name)
        _utc = getattr(instance, "_%s_utc" % self._name)
        _tz = getattr(instance, "_%s_tz" % self._name)
        if isinstance(tz, unicode):
            tz = tz.encode('utf8')
        try:
            timezone = pytz.timezone(tz)
        except pytz_exc, e:
            warnings.warn("Error in timezone: %s" % e)
            setattr(instance, "%s_tz" % self._name, 'UTC')
            timezone = pytz.UTC
        if not dt and not utc:
            # do nothing
            return
        elif dt and dt != _dt:
            utc = UTCDateTimeField.utc_from_localtime(dt, timezone)
            setattr(instance, "%s_utc" % self._name, utc)
        elif utc and (utc != _utc or tz != _tz):
            dt = UTCDateTimeField.localtime_from_utc(utc, timezone)
            setattr(instance, "_%s" % self._name, dt)
        elif not dt:
            dt = UTCDateTimeField.localtime_from_utc(utc, timezone)
            setattr(instance, "_%s" % self._name, dt)
        elif not utc:
            utc = UTCDateTimeField.utc_from_localtime(dt, timezone)
            setattr(instance, "%s_utc" % self._name, utc)
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        if utc.tzinfo:
            utc = utc.replace(tzinfo=None)
        setattr(instance, "_%s" % self._name, dt)
        setattr(instance, "_%s_utc" % self._name, utc)
        setattr(instance, "_%s_tz" % self._name, tz)
        setattr(instance, "%s" % self._name, dt)
        setattr(instance, "%s_utc" % self._name, utc)

    def _model_post_save(self, signal, sender, instance, **kw):
        setattr(instance, "%s" % self._name, getattr(instance, "_%s" % self._name))
        setattr(instance, "%s_utc" % self._name, getattr(instance, "_%s_utc" % self._name))


    def contribute_to_class(self, cls, name):
        self._name = name

        super(UTCDateTimeField, self).contribute_to_class(cls, name)
        self.utc_field = models.DateTimeField(blank=True)
        self.creation_counter = self.utc_field.creation_counter + 1
        models.DateTimeField.contribute_to_class(self.utc_field, cls, '%s_utc' % name)
        self.tz_field = models.CharField(max_length=38, blank=True, choices=TIMEZONES, default=getattr(settings, 'TIME_ZONE', 'UTC'))
        self.creation_counter = self.tz_field.creation_counter + 1
        models.CharField.contribute_to_class(self.tz_field, cls, '%s_tz' % name)

        # add the properties for offset-aware datetimes
        def get_timezone(s):
            tz = getattr(s, '%s_tz' % name)
            if isinstance(tz, unicode):
                tz = tz.encode('utf8')
            return pytz.timezone(tz)
        setattr(cls, "%s_timezone" % name, property(get_timezone))

        def get_dt_offset_aware(s):
            dt = getattr(s, "%s_utc_offset_aware" % name)
            tz = getattr(s, "%s_timezone" % name)
            return dt.astimezone(tz)
        setattr(cls, "%s_offset_aware" % name, property(get_dt_offset_aware))

        def get_utc_offset_aware(s):
            return getattr(s, '%s_utc' % name).replace(tzinfo=pytz.utc)
        setattr(cls, "%s_utc_offset_aware" % name, property(get_utc_offset_aware))

        signals.post_init.connect(self._model_init, sender=cls)
        signals.pre_save.connect(self._model_pre_save, sender=cls)
        signals.post_save.connect(self._model_post_save, sender=cls)

    @staticmethod
    def localtime_from_utc(utc, tz):
        dt = utc.replace(tzinfo=pytz.utc)
        return dt.astimezone(tz)

    @staticmethod
    def utc_from_localtime(dt, tz):
        dt = dt.replace(tzinfo=tz)
        _dt = tz.normalize(dt)
        if dt.tzinfo != _dt.tzinfo:
            # Houston, we have a problem...
            # find out which one has a dst offset
            if _dt.tzinfo.dst(_dt):
                _dt -= _dt.tzinfo.dst(_dt)
            else:
                _dt += dt.tzinfo.dst(dt)
        return _dt.astimezone(pytz.utc)
