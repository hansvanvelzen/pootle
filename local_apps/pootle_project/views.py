#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2008-2009 Zuza Software Foundation
#
# This file is part of Pootle.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.

import locale

from django.utils.translation import ugettext as _
from django.utils.translation import ungettext
from django.shortcuts import get_object_or_404
from django.shortcuts import render_to_response
from django.template import RequestContext
from django import forms
from django.forms.models import BaseModelFormSet
from django.core.exceptions import PermissionDenied

from pootle_misc.baseurl import l
from pootle_project.models import Project
from pootle_statistics.models import Submission
from pootle_app.views.language.view import get_stats_headings
from pootle_app.views.language.item_dict import add_percentages, stats_descriptions
from pootle.i18n.gettext import tr_lang
from pootle_app.views.top_stats import gentopstats
from pootle_app.views import pagelayout
from pootle_translationproject.models import TranslationProject
from pootle_app import project_tree
from pootle_app.views.admin import util
from pootle_profile.models import get_profile
from pootle_app.views.index.index import getprojects
from pootle_app.models.permissions import get_matching_permissions, check_permission
from pootle_app.models import Directory


def limit(query):
    return query[:5]

def get_last_action(translation_project):
    try:
        return Submission.objects.filter(translation_project=translation_project).latest()
    except Submission.DoesNotExist:
        return ''

def make_language_item(request, translation_project):
    href = '/%s/%s/' % (translation_project.language.code, translation_project.project.code)
    projectstats = add_percentages(translation_project.getquickstats())
    info = {
        'code': translation_project.language.code,
        'href': href,
        'title': tr_lang(translation_project.language.fullname),
        'data': projectstats,
        'lastactivity': get_last_action(translation_project),
        'tooltip': _('%(percentage)d%% complete',
                     {'percentage': projectstats['translatedpercentage']})
    }
    errors = projectstats.get('errors', 0)
    if errors:
        info['errortooltip'] = ungettext('Error reading %d file', 'Error reading %d files', errors, errors)
    info.update(stats_descriptions(projectstats))
    return info


def project_language_index(request, project_code):
    """page listing all languages added to project"""
    request.permissions = get_matching_permissions(get_profile(request.user), Directory.objects.root)
    if not check_permission('view', request):
        raise PermissionDenied

    project = get_object_or_404(Project, code=project_code)
    translation_projects = project.translationproject_set.iterator()
    items = [make_language_item(request, translation_project) for translation_project in translation_projects]
    items.sort(lambda x, y: locale.strcoll(x['title'], y['title']))
    languagecount = len(translation_projects)
    totals = add_percentages(project.getquickstats())
    average = totals['translatedpercentage']

    topstats = gentopstats(lambda query: query.filter(translation_project__project__code=project_code))

    templatevars = {
        'project': {
          'code': project.code,
          'name': project.fullname,
          'stats': ungettext('%(languages)d language, %(average)d%% translated',
                             '%(languages)d languages, %(average)d%% translated',
                             languagecount, {"languages": languagecount, "average": average})
        },
        'description': project.description,
        'adminlink': _('Admin'),
        'languages': items,
        'instancetitle': pagelayout.get_title(),
        'topstats': topstats,
        'statsheadings': get_stats_headings(),
        'translationlegend': {'translated': _('Translations are complete'),
                    'fuzzy': _('Translations need to be checked (they are marked fuzzy)'
                    ), 'untranslated': _('Untranslated')},
    }
    return render_to_response('project/project.html', templatevars, context_instance=RequestContext(request))


class TranslationProjectFormSet(BaseModelFormSet):
    def save_existing(self, form, instance, commit=True):
        result = super(TranslationProjectFormSet, self).save_existing(form, instance, commit)
        form.process_extra_fields()
        return result

    def save_new(self, form, commit=True):
        result = super(TranslationProjectFormSet, self).save_new(form, commit)
        form.process_extra_fields()
        return result

@util.user_is_admin
def project_admin(request, project_code):
    """adding and deleting project languages"""
    current_project = Project.objects.get(code=project_code)
    try:
        template_translation_project = TranslationProject.objects.get(project=current_project, language__code='templates')
    except TranslationProject.DoesNotExist:
        template_translation_project = None

    class TranslationProjectForm(forms.ModelForm):
        if template_translation_project is not None:
            update = forms.BooleanField(required=False, label=_("Update from templates"))
        #FIXME: maybe we can detect if initialize is needed to avoid
        # displaying it when not relevant
        initialize = forms.BooleanField(required=False, label=_("Initialize"))
        project = forms.ModelChoiceField(queryset=Project.objects.filter(pk=current_project.pk),
                                         initial=current_project.pk, widget=forms.HiddenInput)
        class Meta:
            prefix = "existing_language"

        def process_extra_fields(self):
            if self.instance.pk is not None:
                if self.cleaned_data.get('initialize', None):
                    self.instance.initialize()

                if self.cleaned_data.get('update', None):
                    project_tree.convert_templates(template_translation_project, self.instance)

    queryset = TranslationProject.objects.filter(project=current_project).order_by('pootle_path')
    model_args = {}
    model_args['project'] = { 'code': current_project.code,
                              'name': current_project.fullname }
    model_args['formid'] = "translation-projects"
    model_args['submitname'] = "changetransprojects"
    link = lambda instance: '<a href="%s">%s</a>' % (l(instance.pootle_path + 'admin_permissions.html'), instance.language)
    return util.edit(request, 'project/project_admin.html', TranslationProject, model_args, link, linkfield="language",
                     queryset=queryset, can_delete=True, form=TranslationProjectForm, formset=TranslationProjectFormSet)


def projects_index(request):
    """page listing all projects"""
    request.permissions = get_matching_permissions(get_profile(request.user), Directory.objects.root)
    if not check_permission('view', request):
        raise PermissionDenied

    topstats = gentopstats(lambda query: query)

    templatevars = {
        'projectlink': _('Projects'),
        'projects': getprojects(request),
        'topstats': topstats,
        'instancetitle': pagelayout.get_title(),
        'translationlegend': {'translated': _('Translations are complete'),
                    'fuzzy': _('Translations need to be checked (they are marked fuzzy)'
                    ), 'untranslated': _('Untranslated')},
        }
    return render_to_response('project/projects.html', templatevars, RequestContext(request))
