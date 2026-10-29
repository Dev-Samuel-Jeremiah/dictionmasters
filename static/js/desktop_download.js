/*
 * The "Download for Windows / Mac / Linux" button on "Get the app"
 * (templates/native_app/_desktop_download.html).
 *
 * The server picks an installer from the browser's description of itself,
 * but that can't tell everything: every Mac browser says "Intel", Safari says
 * macOS 10.15 on every newer Mac, and 32-bit Windows isn't always clear.
 * Where the browser can say more (Chrome and Edge: navigator.userAgentData;
 * otherwise the graphics chip's name), this swaps the button for the right
 * installer, so nobody downloads a file their computer can't run.
 */
(function () {
  var box = document.querySelector("[data-desktop-choice]");
  var data = document.getElementById("desktop-choices");
  if (!box || !data) return;
  var choices = JSON.parse(data.textContent);
  var key = box.getAttribute("data-key");
  var button = box.querySelector("[data-desktop-button]");

  function use(next) {
    if (!choices[next] || next === key) return;
    key = next;
    box.setAttribute("data-key", key);
    button.href = choices[key].url;
    box.querySelector("[data-desktop-os]").textContent = choices[key].os;
    box.querySelector("[data-desktop-detail]").textContent = choices[key].detail;
    var file = box.querySelector("[data-desktop-file]");
    if (file) file.textContent = choices[key].url.split("/").pop();
    box.querySelectorAll("[data-desktop-alt]").forEach(function (link) {
      link.classList.toggle("is-picked", link.getAttribute("data-desktop-alt") === key);
    });
  }

  function graphicsChip() {
    try {
      var gl = document.createElement("canvas").getContext("webgl");
      var info = gl && gl.getExtension("WEBGL_debug_renderer_info");
      return info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL) || "") : "";
    } catch (error) { return ""; }
  }

  function refine(values) {
    var major = parseInt(String(values.platformVersion || "").split(".")[0], 10);
    if (key.indexOf("windows") === 0) {
      // Windows 7 to 8.1 report "0.x"; Windows 10 and 11 report 1 or more.
      if (values.bitness === "32" || major === 0) use("windows_legacy");
      else if (!isNaN(major) && major > 0 && values.architecture) use("windows");
    } else if (key.indexOf("mac") === 0) {
      if (!isNaN(major) && major < 12) use("mac_legacy");
      else if (values.architecture === "arm") use("mac_arm");
      else if (values.architecture === "x86") use("mac_intel");
    }
  }

  box.querySelectorAll("[data-desktop-alt]").forEach(function (link) {
    link.classList.toggle("is-picked", link.getAttribute("data-desktop-alt") === key);
  });

  if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {
    navigator.userAgentData.getHighEntropyValues(["architecture", "bitness", "platformVersion"])
      .then(refine).catch(function () {});
  } else if (key.indexOf("mac") === 0 && key !== "mac_legacy") {
    // Safari and Firefox: the graphics chip says Intel / AMD on an Intel Mac.
    var chip = graphicsChip();
    if (/Apple M\d/i.test(chip)) use("mac_arm");
    else if (/Intel|AMD|Radeon|NVIDIA/i.test(chip)) use("mac_intel");
  }
})();
