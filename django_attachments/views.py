# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json

from django.http import JsonResponse
from django.http.response import HttpResponseRedirect
from django.utils.functional import cached_property
from easy_thumbnails.exceptions import EasyThumbnailsError
from easy_thumbnails.files import get_thumbnailer

from .forms import AttachmentUploadForm, AttachmentUpdateFormSet
from .models import Attachment
from .utils import parse_mimetype


class AttachmentEditableMixin(object):
	upload_form_class = AttachmentUploadForm
	update_form_class = AttachmentUpdateFormSet
	thumbnail_options = {
		'thumbnail': {'crop': True, 'size': (200, 150)},
	}

	def can_upload_attachment(self):
		return True

	def can_update_attachment(self):
		return True

	def get_library(self):
		raise NotImplementedError

	def get_attachment_form_kwargs(self, action, **extra_kwargs):
		kwargs = {}
		kwargs.update(extra_kwargs)
		if self.request.POST.get('action') == action:
			kwargs.update({
				'data': self.request.POST,
				'files': self.request.FILES,
			})
		return kwargs

	def get_upload_form_kwargs(self):
		return self.get_attachment_form_kwargs('upload', library=self.get_library())

	def get_update_form_kwargs(self):
		library = self.get_library()
		if library:
			queryset = library.attachment_set.all()
		else:
			queryset = Attachment.objects.none()
		return self.get_attachment_form_kwargs('update', queryset=queryset)

	@cached_property
	def upload_form(self):
		if self.can_upload_attachment():
			return self.upload_form_class(**self.get_upload_form_kwargs())
		else:
			return None

	@cached_property
	def update_form(self):
		if self.can_update_attachment():
			return self.update_form_class(**self.get_update_form_kwargs())
		else:
			return None

	def get_context_data(self, **kwargs):
		ctx = super(AttachmentEditableMixin, self).get_context_data(**kwargs)
		ctx['upload_form'] = self.upload_form
		ctx['update_form'] = self.update_form
		return ctx

	def post(self, request, *args, **kwargs):
		action = self.request.POST.get('action')
		if action == 'upload' and self.upload_form:
			if self.upload_form.is_valid():
				return self.upload_form_valid(self.upload_form)
			else:
				return self.upload_form_invalid(self.upload_form)
		if action == 'update' and self.upload_form:
			if self.update_form.is_valid():
				return self.update_form_valid(self.update_form)
			else:
				return self.update_form_invalid(self.update_form)
		if action == 'mimetype':
			filename = self.request.POST.get('filename')
			mimetype = parse_mimetype(filename)
			return JsonResponse(mimetype)
		return super(AttachmentEditableMixin, self).post(request, *args, **kwargs)

	def upload_form_valid(self, form):
		upload = form.save()
		self.update_primary_attachment()
		if self.request.is_ajax():
			attachments = self.serialize_attachemnts()
			for attachment in attachments:
				attachment['is_new'] = upload.id == attachment['id']
			return JsonResponse({'attachments': attachments})
		return HttpResponseRedirect(self.request.get_full_path())

	def upload_form_invalid(self, form):
		if self.request.is_ajax():
			return JsonResponse({'errors': json.loads(form.errors.as_json())})
		return self.render_to_response(self.get_context_data())

	def update_form_valid(self, form):
		form.save()
		self.update_primary_attachment()
		if self.request.is_ajax():
			return self.render_json_attachments()
		return HttpResponseRedirect(self.request.get_full_path())

	def update_form_invalid(self, form):
		if self.request.is_ajax():
			errors = {}
			for subform in form:
				errors.update(json.loads(subform.errors.as_json()))
			return JsonResponse({'errors': errors})
		return self.render_to_response(self.get_context_data())

	def get(self, request, *args, **kwargs):
		if self.request.is_ajax():
			return self.render_json_attachments()
		return super(AttachmentEditableMixin, self).get(request, *args, **kwargs)

	def serialize_attachemnts(self):
		library = self.get_library()
		if not library or not library.pk:
			return []
		attachments = library.attachment_set.all()
		attachments_data = []
		for attachment in attachments:
			attachment_data = {
				'id': attachment.pk,
				'name': attachment.original_name,
				'rank': attachment.rank,
				'filesize': attachment.filesize,
				'mimetype': attachment.mimetype,
				'mimetype_url': parse_mimetype(attachment.original_name)['mimetype_url'],
			}
			if attachment.is_image:
				attachment_data['image_width'] = attachment.image_width
				attachment_data['image_height'] = attachment.image_height
				thumbnailer = get_thumbnailer(attachment.file)
				for key, options in self.thumbnail_options.items():
					try:
						attachment_data[key] = thumbnailer.get_thumbnail(options).url
					except EasyThumbnailsError:
						attachment_data[key] = None
			attachments_data.append(attachment_data)
		return attachments_data

	def render_json_attachments(self):
		return JsonResponse({'attachments': self.serialize_attachemnts()})

	def update_primary_attachment(self):
		library = self.get_library()
		if not library.pk:
			return
		library.refresh_from_db()
		first_attachment = library.attachment_set.order_by('rank').first()
		if library.primary_attachment != first_attachment:
			library.primary_attachment = first_attachment
			library.save()
