# Copyright (C) 2018 Intel Corporation
#
# SPDX-License-Identifier: MIT

from django.db import models
from django.conf import settings

from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage

from io import StringIO
from enum import Enum

import shlex
import csv
import re
import os
import sys


class StatusChoice(str, Enum):
    ANNOTATION = 'annotation'
    VALIDATION = 'validation'
    COMPLETED = 'completed'

    @classmethod
    def choices(self):
        return tuple((x.name, x.value) for x in self)

class SafeCharField(models.CharField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value:
            return value[:self.max_length]
        return value

class Task(models.Model):
    name = SafeCharField(max_length=256)
    size = models.PositiveIntegerField()
    mode = models.CharField(max_length=32)
    owner = models.ForeignKey(User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owners")
    assignee = models.ForeignKey(User, null=True,  blank=True,
        on_delete=models.SET_NULL, related_name="assignees")
    bug_tracker = models.CharField(max_length=2000, blank=True, default="")
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now_add=True)
    overlap = models.PositiveIntegerField(default=0)
    segment_size = models.PositiveIntegerField()
    z_order = models.BooleanField(default=False)
    flipped = models.BooleanField(default=False)
    image_quality = models.PositiveSmallIntegerField()
    # FIXME: remote source field
    source = SafeCharField(max_length=256, default="unknown")
    status = models.CharField(max_length=32, choices=StatusChoice.choices(),
        default=StatusChoice.ANNOTATION)

    # Extend default permission model
    class Meta:
        default_permissions = ()

    def get_upload_dirname(self):
        return os.path.join(self.get_task_dirname(), ".upload")

    def get_data_dirname(self):
        return os.path.join(self.get_task_dirname(), "data")

    def get_dump_path(self):
        name = re.sub(r'[\\/*?:"<>|]', '_', self.name)
        return os.path.join(self.get_task_dirname(), "{}.xml".format(name))

    def get_log_path(self):
        return os.path.join(self.get_task_dirname(), "task.log")

    def get_client_log_path(self):
        return os.path.join(self.get_task_dirname(), "client.log")

    def get_image_meta_cache_path(self):
        return os.path.join(self.get_task_dirname(), "image_meta.cache")

    def get_task_dirname(self):
        return os.path.join(settings.DATA_ROOT, str(self.id))

    def __str__(self):
        return self.name

def upload_path_handler(instance, filename):
    return os.path.join(instance.task.get_upload_dirname(), filename)

# For client files which the user is uploaded
class ClientFile(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    file = models.FileField(upload_to=upload_path_handler,
        storage=FileSystemStorage())

    class Meta:
        default_permissions = ()

# For server files on the mounted share
class ServerFile(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    file = models.CharField(max_length=1024)

    class Meta:
        default_permissions = ()

# For URLs
class RemoteFile(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    file = models.CharField(max_length=1024)

    class Meta:
        default_permissions = ()


class Segment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    start_frame = models.IntegerField()
    stop_frame = models.IntegerField()

    class Meta:
        default_permissions = ()

class Job(models.Model):
    segment = models.ForeignKey(Segment, on_delete=models.CASCADE)
    assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=32, default=StatusChoice.ANNOTATION)
    max_shape_id = models.BigIntegerField(default=-1)

    class Meta:
        default_permissions = ()

class Label(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    name = SafeCharField(max_length=64)

    def __str__(self):
        return self.name

    class Meta:
        default_permissions = ()
        unique_together = ('task', 'name')

# FIXME: need to remote text and add (name, type, permanent,
# default_value, values)
class AttributeSpec(models.Model):
    label = models.ForeignKey(Label, on_delete=models.CASCADE)
    text  = models.CharField(max_length=1024)

    class Meta:
        default_permissions = ()
        # FIXME: unique_together = ('label', 'name')

    @classmethod
    def parse(cls, value):
        match = re.match(r'^([~@])(\w+)=(\w+):(.+)?$', value)
        if match:
            prefix = match.group(1)
            type = match.group(2)
            name = match.group(3)
            if match.group(4):
                values = list(csv.reader(StringIO(match.group(4)),
                    quotechar="'"))[0]
            else:
                values = []

            return {'prefix':prefix, 'type':type, 'name':name, 'values':values}
        else:
            return None

    def get_attribute(self):
        return self.parse(self.text)

    def is_mutable(self):
        attr = self.get_attribute()
        return attr['prefix'] == '~'

    def get_type(self):
        attr = self.get_attribute()
        return attr['type']

    def get_name(self):
        attr = self.get_attribute()
        return attr['name']

    def get_default_value(self):
        attr = self.get_attribute()
        return attr['values'][0]

    def get_values(self):
        attr = self.get_attribute()
        return attr['values']

    def __str__(self):
        return self.get_attribute()['name']


class AttributeVal(models.Model):
    # TODO: add a validator here to be sure that it corresponds to self.label
    id = models.BigAutoField(primary_key=True)
    spec = models.ForeignKey(AttributeSpec, on_delete=models.CASCADE)
    value = SafeCharField(max_length=64)

    class Meta:
        abstract = True
        default_permissions = ()


class Annotation(models.Model):
    job   = models.ForeignKey(Job, on_delete=models.CASCADE)
    label = models.ForeignKey(Label, on_delete=models.CASCADE)
    frame = models.PositiveIntegerField()
    group_id = models.PositiveIntegerField(default=0)
    client_id = models.BigIntegerField(default=-1)

    class Meta:
        abstract = True

class Shape(models.Model):
    occluded = models.BooleanField(default=False)
    z_order = models.IntegerField(default=0)

    class Meta:
        abstract = True
        default_permissions = ()

class BoundingBox(Shape):
    id = models.BigAutoField(primary_key=True)
    xtl = models.FloatField()
    ytl = models.FloatField()
    xbr = models.FloatField()
    ybr = models.FloatField()

    class Meta:
        abstract = True
        default_permissions = ()

class PolyShape(Shape):
    id = models.BigAutoField(primary_key=True)
    points = models.TextField()

    class Meta:
        abstract = True
        default_permissions = ()

class LabeledBox(Annotation, BoundingBox):
    pass

class LabeledBoxAttributeVal(AttributeVal):
    box = models.ForeignKey(LabeledBox, on_delete=models.CASCADE)

class LabeledPolygon(Annotation, PolyShape):
    pass

class LabeledPolygonAttributeVal(AttributeVal):
    polygon = models.ForeignKey(LabeledPolygon, on_delete=models.CASCADE)

class LabeledPolyline(Annotation, PolyShape):
    pass

class LabeledPolylineAttributeVal(AttributeVal):
    polyline = models.ForeignKey(LabeledPolyline, on_delete=models.CASCADE)

class LabeledPoints(Annotation, PolyShape):
    pass

class LabeledPointsAttributeVal(AttributeVal):
    points = models.ForeignKey(LabeledPoints, on_delete=models.CASCADE)

class ObjectPath(Annotation):
    id = models.BigAutoField(primary_key=True)
    shapes = models.CharField(max_length=10, default='boxes')

class ObjectPathAttributeVal(AttributeVal):
    track = models.ForeignKey(ObjectPath, on_delete=models.CASCADE)

class TrackedObject(models.Model):
    track = models.ForeignKey(ObjectPath, on_delete=models.CASCADE)
    frame = models.PositiveIntegerField()
    outside = models.BooleanField(default=False)
    class Meta:
        abstract = True
        default_permissions = ()

class TrackedBox(TrackedObject, BoundingBox):
    pass

class TrackedBoxAttributeVal(AttributeVal):
    box = models.ForeignKey(TrackedBox, on_delete=models.CASCADE)

class TrackedPolygon(TrackedObject, PolyShape):
    pass

class TrackedPolygonAttributeVal(AttributeVal):
    polygon = models.ForeignKey(TrackedPolygon, on_delete=models.CASCADE)

class TrackedPolyline(TrackedObject, PolyShape):
    pass

class TrackedPolylineAttributeVal(AttributeVal):
    polyline = models.ForeignKey(TrackedPolyline, on_delete=models.CASCADE)

class TrackedPoints(TrackedObject, PolyShape):
    pass

class TrackedPointsAttributeVal(AttributeVal):
    points = models.ForeignKey(TrackedPoints, on_delete=models.CASCADE)

class Plugin(models.Model):
    name = models.SlugField(max_length=32, primary_key=True)
    description = SafeCharField(max_length=8192)
    maintainer = models.ForeignKey(User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="maintainers")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    # Extend default permission model
    class Meta:
        default_permissions = ()

class PluginOption(models.Model):
    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE)
    name = SafeCharField(max_length=32)
    value = SafeCharField(max_length=1024)