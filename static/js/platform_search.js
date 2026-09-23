(() => {
  const forms = document.querySelectorAll("[data-search-autocomplete]");
  if (!forms.length) return;

  forms.forEach((form, formIndex) => {
    const input = form.querySelector('input[name="q"]');
    if (!input) return;

    const listId = `search-suggestions-${formIndex + 1}`;
    const list = document.createElement("div");
    list.className = "search-suggestions";
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    form.append(list);

    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", listId);
    input.setAttribute("aria-expanded", "false");

    let timer;
    let controller;
    let activeIndex = -1;
    let requestNumber = 0;

    const close = () => {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
    };

    const showMessage = (message) => {
      list.replaceChildren();
      const status = document.createElement("div");
      status.className = "search-suggestions__message";
      status.setAttribute("role", "status");
      status.textContent = message;
      list.append(status);
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      activeIndex = -1;
    };

    const setActive = (index) => {
      const options = list.querySelectorAll("[role='option']");
      if (!options.length) return;
      activeIndex = (index + options.length) % options.length;
      options.forEach((option, i) => option.setAttribute("aria-selected", String(i === activeIndex)));
      input.setAttribute("aria-activedescendant", options[activeIndex].id);
    };

    const render = (results) => {
      list.replaceChildren();
      if (!results.length) {
        showMessage("No matching suggestions. Press Enter to view search results.");
        return;
      }

      results.forEach((result, index) => {
        const link = document.createElement("a");
        link.className = "search-suggestion";
        link.href = result.url;
        link.id = `${listId}-option-${index + 1}`;
        link.setAttribute("role", "option");
        link.setAttribute("aria-selected", "false");

        const heading = document.createElement("strong");
        heading.textContent = result.title;
        const type = document.createElement("span");
        type.className = "search-suggestion__type";
        type.textContent = result.section;
        link.append(heading, type);
        if (result.summary) {
          const summary = document.createElement("span");
          summary.className = "search-suggestion__summary";
          summary.textContent = result.summary;
          link.append(summary);
        }
        list.append(link);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      activeIndex = -1;
    };

    input.addEventListener("input", () => {
      window.clearTimeout(timer);
      if (controller) controller.abort();
      const query = input.value.trim();
      if (query.length < 2) {
        close();
        return;
      }

      timer = window.setTimeout(async () => {
        const currentRequest = ++requestNumber;
        controller = new AbortController();
        try {
          const url = new URL(form.dataset.searchAutocomplete, window.location.origin);
          url.searchParams.set("q", query);
          const response = await fetch(url, {
            headers: { "Accept": "application/json" },
            signal: controller.signal,
          });
          if (!response.ok) throw new Error("Search suggestions unavailable");
          const data = await response.json();
          if (currentRequest === requestNumber && input.value.trim() === query) render(data.results || []);
        } catch (error) {
          if (error.name !== "AbortError" && currentRequest === requestNumber) close();
        }
      }, 260);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        close();
      } else if (event.key === "ArrowDown" && !list.hidden) {
        event.preventDefault();
        setActive(activeIndex + 1);
      } else if (event.key === "ArrowUp" && !list.hidden) {
        event.preventDefault();
        setActive(activeIndex < 0 ? list.querySelectorAll("[role='option']").length - 1 : activeIndex - 1);
      } else if (event.key === "Enter" && activeIndex >= 0) {
        const option = list.querySelectorAll("[role='option']")[activeIndex];
        if (option) window.location.assign(option.href);
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!form.contains(event.target)) close();
    });
  });
})();
