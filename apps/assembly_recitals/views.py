"""Assembly Recitals: the sections, a section's recitals, one recital."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render

from .models import Recital, Section


def _published_sections():
    return Section.objects.filter(is_published=True).annotate(
        recital_count=Count("recitals", filter=Q(recitals__is_published=True))
    ).order_by("order", "name")


@login_required
def hub(request):
    sections = list(_published_sections())
    return render(request, "assembly_recitals/hub.html", {
        "sections": sections,
        "recital_total": sum(s.recital_count for s in sections),
    })


@login_required
def section_detail(request, section_slug):
    section = get_object_or_404(Section, slug=section_slug, is_published=True)
    recitals = section.recitals.filter(is_published=True)
    return render(request, "assembly_recitals/section.html", {
        "section": section,
        "recitals": recitals,
        "sections": _published_sections(),
    })


@login_required
def recital_detail(request, section_slug, recital_slug):
    section = get_object_or_404(Section, slug=section_slug, is_published=True)
    recital = get_object_or_404(Recital, section=section, slug=recital_slug, is_published=True)
    siblings = list(section.recitals.filter(is_published=True))
    index = next((i for i, r in enumerate(siblings) if r.pk == recital.pk), 0)
    return render(request, "assembly_recitals/recital.html", {
        "section": section,
        "recital": recital,
        "verses": recital.verses,
        "prev_recital": siblings[index - 1] if index > 0 else None,
        "next_recital": siblings[index + 1] if index < len(siblings) - 1 else None,
        "position": index + 1,
        "count": len(siblings),
    })
