from optparse import make_option
import os
from os.path import abspath, dirname, exists, join
import shutil

from django.conf import settings
from django.core.management.base import CommandError
import django.core.management.commands.dumpdata
import django.core.serializers
from django.db.models.fields.files import FileField
import django.dispatch

from fixturemedia.management.commands.loaddata import models_with_filefields


pre_dump = django.dispatch.Signal(providing_args=('instance',))


class Command(django.core.management.commands.dumpdata.Command):

    option_list = django.core.management.commands.dumpdata.Command.option_list + (
        make_option('--outfile', dest='outfile',
            help='Specifies the file to write the serialized items to (required)'),
    )

    def save_images_for_signal(self, sender, **kwargs):
        instance = kwargs['instance']
        for field in sender._meta.fields:
            if not isinstance(field, FileField):
                continue
            path = getattr(instance, field.attname)
            if path is None or not path.name:
                continue

            source_path = join(settings.MEDIA_ROOT, path.name)
            if not exists(source_path):
                continue

            target_path = join(self.target_dir, path.name)
            if not exists(dirname(target_path)):
                os.makedirs(dirname(target_path))

            try:
                shutil.copy(source_path, target_path)
            except FileNotFoundError:
                self.stderr.write("Expected file at {} doesn't exist, skipping".format(source_path))
                continue

    def set_up_serializer(self, ser_format):
        try:
            super_serializer = django.core.serializers.get_serializer(ser_format)
            super_deserializer = django.core.serializers.get_deserializer(ser_format)
        except KeyError:
            raise CommandError("Unknown serialization format: {}".format(ser_format))

        global Serializer, Deserializer

        class Serializer(super_serializer):
            def get_dump_object(self, obj):
                pre_dump.send(sender=type(obj), instance=obj)
                return super(Serializer, self).get_dump_object(obj)

        # We don't care about deserializing.
        Deserializer = super_deserializer

        django.core.serializers.register_serializer(ser_format,
             'fixturemedia.management.commands.dumpdata')

    def handle(self, *app_labels, **options):
        ser_format = options.get('format')

        outfilename = options.get('outfile')
        if outfilename is None:
            raise CommandError('No --outfile specified (this is a required option)')
        self.target_dir = join(dirname(abspath(outfilename)), 'media')

        for modelclass in models_with_filefields():
            pre_dump.connect(self.save_images_for_signal, sender=modelclass)

        self.set_up_serializer(ser_format)

        with open(outfilename, 'w') as self.stdout:
            super(Command, self).handle(*app_labels, **options)
