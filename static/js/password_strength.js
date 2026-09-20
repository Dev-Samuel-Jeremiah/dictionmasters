/* Choosing a password, with help.

   Under the password box on every page where one is set, this shows:

     * the four things the site actually checks, ticking off as they are
       met — the same four Django checks the form will apply when it is
       sent, so nothing is accepted here and refused there;
     * how strong the password is, as a bar and a word;
     * an example, and a button that makes a good one and fills both
       boxes, for anyone who would rather not think of one.

   The confirm box says whether the two match, so nobody finds out only
   after pressing the button.

   Without this script the boxes still work and the written guidance under
   them still says what is wanted.  */

(function () {
  "use strict";

  // Enough of the commonest passwords to catch a bad habit while typing.
  // The site itself checks against Django's full list of 20,000 when the
  // form is sent, so this only has to be a warning in good time.
  var COMMON = ("password passw0rd password1 password123 123456 1234567 12345678 123456789 1234567890 " +
    "qwerty qwertyuiop asdfgh zxcvbnm 111111 000000 123123 abc123 abcd1234 a1b2c3 iloveyou princess " +
    "admin administrator welcome welcome1 monkey dragon sunshine football baseball letmein trustno1 " +
    "starwars whatever qazwsx michael jennifer jordan superman batman pokemon computer internet samsung " +
    "google master shadow killer hello hello123 freedom ninja mustang harley ranger buster soccer " +
    "hockey tigger charlie andrew thomas robert daniel joshua matthew nicole hunter cookie summer " +
    "chelsea maggie jessica pepper ginger banana orange purple qwerty123 1q2w3e4r 1qaz2wsx zaq12wsx " +
    "nigeria naija lagos chelsea2 arsenal manchester barcelona realmadrid jesus jesuschrist godislove " +
    "amen blessing precious goodluck emmanuel chinedu chidinma ifeanyi olamide wizkid davido"
  ).split(" ");

  var WORDS = ("mango river sunrise market lantern pepper basket garden thunder harvest copper " +
    "melon pebble candle forest meadow anchor bridge cotton feather ginger hammer island jungle " +
    "kettle ladder marble needle orchard parrot quartz rocket saddle temple violet walnut yellow " +
    "zebra cocoa palm drum yam okra maize sparrow sandal ribbon tunnel velvet window"
  ).split(" ");

  var LEVELS = ["Too short", "Weak", "Fair", "Strong", "Very strong"];

  function text(node) { return (node && node.value ? String(node.value) : "").trim(); }

  function form(input) { return input.form || input.closest("form") || document; }

  function personalBits(input) {
    /* The name and email already typed on this form: a password built out
       of them is the first thing anyone would try, and the site refuses
       it, so it is refused here too. */
    var bits = [];
    var scope = form(input);
    var names = ["first_name", "last_name", "email", "school_name", "school_email",
                 "child_first_name", "child_last_name", "username"];
    names.forEach(function (name) {
      var field = scope.querySelector ? scope.querySelector("[name$='" + name + "']") : null;
      var value = text(field).toLowerCase();
      if (value.length < 3) return;
      bits.push(value);
      value.split(/[@.\s_-]+/).forEach(function (piece) { if (piece.length >= 3) bits.push(piece); });
    });
    return bits;
  }

  function sameness(a, b) {
    // How alike two words are, 0 to 1 — close to what the site works out.
    if (!a || !b) return 0;
    var rows = a.length + 1, cols = b.length + 1;
    var previous = new Array(cols).fill(0), current = new Array(cols).fill(0);
    var longest = 0;
    for (var i = 1; i < rows; i++) {
      for (var j = 1; j < cols; j++) {
        current[j] = a[i - 1] === b[j - 1] ? previous[j - 1] + 1 : 0;
        if (current[j] > longest) longest = current[j];
      }
      previous = current.slice();
    }
    return (2 * longest) / (a.length + b.length);
  }

  function judge(password, personal) {
    var lower = password.toLowerCase();
    var checks = [
      { key: "length", label: "8 characters or more", ok: password.length >= 8 },
      { key: "numbers", label: "Not only numbers", ok: !/^\d+$/.test(password) && password.length > 0 },
      { key: "common", label: "Not a common password", ok: password.length > 0 && COMMON.indexOf(lower) < 0 },
      {
        key: "personal", label: "Not your name or email", ok: password.length > 0 && !personal.some(function (bit) {
          return lower === bit || sameness(lower, bit) > 0.7;
        }),
      },
    ];

    var kinds = 0;
    [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].forEach(function (pattern) { if (pattern.test(password)) kinds += 1; });
    var score = 0;
    if (password.length >= 8) {
      score = 1;
      if (password.length >= 10 && kinds >= 2) score = 2;
      if (password.length >= 12 && kinds >= 2) score = 3;
      if (password.length >= 14 && kinds >= 3) score = 4;
      if (/^(.)\1+$/.test(password) || /^(?:012|123|234|345|456|567|678|789|890|abc|qwe)/.test(password.toLowerCase())) {
        score = 1;
      }
    }
    if (checks.some(function (check) { return !check.ok; })) score = Math.min(score, 1);
    return { checks: checks, score: score, accepted: checks.every(function (check) { return check.ok; }) };
  }

  function madeUpPassword() {
    var numbers = new Uint32Array(3);
    (window.crypto || window.msCrypto).getRandomValues(numbers);
    var first = WORDS[numbers[0] % WORDS.length];
    var second = WORDS[numbers[1] % WORDS.length];
    var digits = 10 + (numbers[2] % 90);
    if (first === second) second = WORDS[(numbers[1] + 1) % WORDS.length];
    return first + "-" + second + "-" + digits;
  }

  function el(tag, className, inner) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (inner !== undefined) node.innerHTML = inner;
    return node;
  }

  function build(input) {
    if (input.dataset.pwGuide) return;
    input.dataset.pwGuide = "1";

    var field = input.closest(".field") || input.parentNode;
    var written = field.querySelector(".field-help");     // the written guidance
    var panel = el("div", "pw-guide");
    panel.id = (input.id || "password") + "-guide";

    panel.appendChild(el("div", "pw-meter",
      '<span class="pw-meter__bar"><span class="pw-meter__fill" data-fill></span></span>' +
      '<span class="pw-meter__word" data-word aria-live="polite">Type a password</span>'));

    var list = el("ul", "pw-rules");
    judge("", []).checks.forEach(function (check) {
      var item = el("li", "pw-rule", '<span class="pw-rule__mark" aria-hidden="true"></span><span>' + check.label + "</span>");
      item.dataset.rule = check.key;
      list.appendChild(item);
    });
    panel.appendChild(list);

    panel.appendChild(el("p", "pw-example",
      'For example: <strong>mango river 47</strong> or <strong>Blue-Gate-8</strong> — easy for you, hard for anyone else.'));

    var make = el("button", "pw-make", "Suggest a strong password");
    make.type = "button";
    panel.appendChild(make);
    var made = el("p", "pw-made");
    made.hidden = true;
    panel.appendChild(made);

    if (written) written.remove();          // the panel says it better
    field.appendChild(panel);
    input.setAttribute("aria-describedby", panel.id);

    var fill = panel.querySelector("[data-fill]");
    var word = panel.querySelector("[data-word]");

    function confirmBox() {
      var scope = form(input);
      var name = (input.getAttribute("name") || "").replace(/1$/, "2");
      return scope.querySelector ? scope.querySelector("[name='" + name + "']") : null;
    }

    function show() {
      var password = input.value || "";
      var verdict = judge(password, personalBits(input));
      panel.querySelectorAll(".pw-rule").forEach(function (item) {
        var check = verdict.checks.filter(function (one) { return one.key === item.dataset.rule; })[0];
        item.classList.toggle("is-met", Boolean(password && check && check.ok));
        item.classList.toggle("is-missing", Boolean(password && check && !check.ok));
      });
      fill.style.width = (password ? (verdict.score + 1) * 20 : 0) + "%";
      panel.dataset.score = password ? verdict.score : "";
      panel.classList.toggle("is-accepted", verdict.accepted);
      word.textContent = !password ? "Type a password"
        : verdict.accepted ? LEVELS[verdict.score] + " — you can use this password"
        : LEVELS[verdict.score] + " — see what's missing below";
      matched();
    }

    function matched() {
      var confirm = confirmBox();
      if (!confirm) return;
      var note = confirm.closest(".field") ? confirm.closest(".field").querySelector(".pw-match") : null;
      if (!note) {
        note = el("p", "pw-match");
        (confirm.closest(".field") || confirm.parentNode).appendChild(note);
      }
      if (!confirm.value) { note.textContent = ""; note.className = "pw-match"; return; }
      var same = confirm.value === input.value;
      note.textContent = same ? "Both boxes match." : "The two passwords don't match yet.";
      note.className = "pw-match " + (same ? "is-same" : "is-different");
    }

    make.addEventListener("click", function () {
      var password = madeUpPassword();
      input.value = password;
      var confirm = confirmBox();
      if (confirm) confirm.value = password;
      made.hidden = false;
      made.innerHTML = 'Your password is <strong>' + password + '</strong> — write it down somewhere safe.';
      show();
      input.focus();
    });

    input.addEventListener("input", show);
    input.addEventListener("blur", show);
    var confirm = confirmBox();
    if (confirm) confirm.addEventListener("input", matched);
    form(input).addEventListener("input", function (event) {
      var name = event.target.getAttribute && event.target.getAttribute("name");
      if (name && /first_name|last_name|email|school_name/.test(name)) show();
    });
    show();
  }

  function start() {
    // Only where a password is being set — never on the sign-in page.
    document.querySelectorAll("input[type=password]").forEach(function (input) {
      var name = input.getAttribute("name") || "";
      if (/password1$|new_password1$/.test(name)) build(input);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
