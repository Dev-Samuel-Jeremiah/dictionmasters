from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from .models import LibraryArticle, LibraryCategory


@login_required
def home(request):
    query = request.GET.get("q", "").strip()
    categories = LibraryCategory.objects.order_by("order")

    results = None
    if query:
        results = (
            LibraryArticle.objects.filter(is_published=True)
            .filter(
                Q(title__icontains=query)
                | Q(summary__icontains=query)
                | Q(body__icontains=query)
                | Q(tags__name__icontains=query)
            )
            .select_related("category")
            .distinct()
            .order_by("title")
        )

    recent_articles = None
    if not query:
        recent_articles = (
            LibraryArticle.objects.filter(is_published=True)
            .select_related("category")
            .order_by("-updated_at")[:6]
        )

    context = {
        "query": query,
        "categories": categories,
        "results": results,
        "recent_articles": recent_articles,
    }
    return render(request, "reference_library/home.html", context)


@login_required
def category_detail(request, slug):
    category = get_object_or_404(LibraryCategory, slug=slug)
    articles = category.articles.filter(is_published=True).order_by("order", "title")
    return render(request, "reference_library/category.html", {"category": category, "articles": articles})


@login_required
def article_detail(request, slug):
    article = get_object_or_404(
        LibraryArticle.objects.select_related("category").prefetch_related("tags", "attachments"),
        slug=slug,
        is_published=True,
    )
    return render(request, "reference_library/article.html", {"article": article})
