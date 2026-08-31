document.addEventListener("DOMContentLoaded", function () {
  // ============ Mobile nav toggle ============
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      links.classList.toggle("show");
    });
  }

  // ============ Menu category filter ============
  var filterButtons = document.querySelectorAll(".filter-btn");
  var menuCards = document.querySelectorAll("[data-category]");
  if (filterButtons.length && menuCards.length) {
    filterButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        filterButtons.forEach(function (b) {
          b.classList.remove("active");
        });
        btn.classList.add("active");
        var target = btn.getAttribute("data-filter");
        menuCards.forEach(function (card) {
          if (target === "all" || card.getAttribute("data-category") === target) {
            card.style.display = "";
          } else {
            card.style.display = "none";
          }
        });
      });
    });
  }

  initSliders();
});

// ============================================================
// Navbar cart badge (reusable everywhere a cart AJAX call lands)
// ============================================================
function updateCartBadge(cartCount) {
  var cartBtn = document.querySelector(".cart-btn");
  if (!cartBtn) return;

  var badge = cartBtn.querySelector(".cart-count");

  if (cartCount > 0) {
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "cart-count";
      cartBtn.appendChild(badge);
    }
    badge.textContent = cartCount;
  } else if (badge) {
    badge.remove();
  }
}

// ============================================================
// Menu page (and home page Popular Dishes slider): cart add/quantity
// sync via AJAX, backend-driven.
// ============================================================
// Progressive enhancement only: every form below has a real action URL and
// works as a normal POST+redirect without JS. When JS is available we
// intercept the submit, hit the same backend endpoint, and patch just the
// cart-controls for that item so "Add Item" <-> quantity controls swap
// immediately, per the actual cart state the backend returns.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".food-cart-controls").forEach(function (container) {
    container.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form.matches(".cart-add-form, .menu-qty-form")) return;

      event.preventDefault();

      var formData = new FormData(form, event.submitter || undefined);

      postCartAction(form.getAttribute("action"), formData)
        .then(function (data) {
          renderCartControls(container, data);
        })
        .catch(function () {
          // Network/parse failure: fall back to a normal full-page submit
          // so the user's action isn't silently lost.
          form.submit();
        });
    });
  });
});

function postCartAction(url, formData) {
  return fetch(url, {
    method: "POST",
    headers: { "X-Requested-With": "XMLHttpRequest" },
    body: formData,
  }).then(function (response) {
    return response.json();
  });
}

function renderCartControls(container, data) {
  if (!data.ok) {
    if (data.error) {
      window.alert(data.error);
    }
    return;
  }

  updateCartBadge(data.cart_count);

  var addUrl = container.getAttribute("data-add-url");
  var updateUrlTemplate = container.getAttribute("data-update-url-template");
  var csrfInput = container.querySelector('input[name="csrfmiddlewaretoken"]');
  var csrfValue = csrfInput ? csrfInput.value : "";

  if (data.in_cart) {
    var updateUrl = updateUrlTemplate.replace("999999999", data.cart_item_id);
    container.innerHTML =
      '<form action="' + updateUrl + '" method="POST" class="menu-qty-form cart-qty-form">' +
      '<input type="hidden" name="csrfmiddlewaretoken" value="' + csrfValue + '">' +
      '<input type="hidden" name="origin" value="menu">' +
      '<button type="submit" name="quantity" value="' + (data.quantity - 1) + '" class="qty-btn">\u2212</button>' +
      '<span class="menu-qty">' + data.quantity + '</span>' +
      '<button type="submit" name="quantity" value="' + (data.quantity + 1) + '" class="qty-btn">+</button>' +
      '</form>';
  } else {
    container.innerHTML =
      '<form action="' + addUrl + '" method="POST" class="cart-add-form">' +
      '<input type="hidden" name="csrfmiddlewaretoken" value="' + csrfValue + '">' +
      '<button class="add-btn" type="submit">+ Add</button>' +
      '</form>';
  }
}

// ============================================================
// Cart page: quantity +/- and remove, via the same AJAX endpoints,
// with the row/summary/navbar badge all kept in sync -- no reload.
// ============================================================
document.addEventListener("DOMContentLoaded", function () {
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches(".cart-qty-form, .cart-remove-form")) return;
    // Menu-page quantity forms are already handled by the
    // .food-cart-controls listener above.
    if (form.closest(".food-cart-controls")) return;

    event.preventDefault();

    var formData = new FormData(form, event.submitter || undefined);

    postCartAction(form.getAttribute("action"), formData)
      .then(function (data) {
        applyCartRowUpdate(form, data);
      })
      .catch(function () {
        form.submit();
      });
  });
});

function applyCartRowUpdate(form, data) {
  if (!data.ok) {
    if (data.error) {
      window.alert(data.error);
    }
    return;
  }

  updateCartBadge(data.cart_count);

  var row = form.closest("tr[data-cart-row]");
  if (!row) return;

  if (!data.in_cart) {
    row.remove();
    recalcCartSummary();
    return;
  }

  var qtyInput = row.querySelector(".qty-control input[type='text']");
  if (qtyInput) qtyInput.value = data.quantity;

  row.querySelectorAll(".cart-qty-form").forEach(function (qtyForm) {
    var hidden = qtyForm.querySelector("input[name='quantity']");
    if (!hidden) return;
    var isMinus = qtyForm.querySelector(".qty-minus") !== null;
    hidden.value = isMinus ? Math.max(data.quantity - 1, 0) : data.quantity + 1;
  });

  recalcCartSummary();
}

function recalcCartSummary() {
  var tbody = document.getElementById("cart-tbody");
  if (!tbody) return;

  var rows = tbody.querySelectorAll("tr[data-cart-row]");
  var subtotal = 0;

  rows.forEach(function (row) {
    var price = parseFloat(row.getAttribute("data-price")) || 0;
    var qtyInput = row.querySelector(".qty-control input[type='text']");
    var qty = qtyInput ? parseInt(qtyInput.value, 10) || 0 : 0;
    var rowTotal = price * qty;

    var totalCell = row.querySelector("[data-row-total]");
    if (totalCell) totalCell.textContent = "\u20b9" + rowTotal.toFixed(0);

    subtotal += rowTotal;
  });

  var deliveryFee = subtotal > 0 ? 40 : 0;
  var total = subtotal + deliveryFee;

  var subtotalEl = document.querySelector("[data-subtotal]");
  var deliveryEl = document.querySelector("[data-delivery-fee]");
  var totalEl = document.querySelector("[data-total]");
  var checkoutBtn = document.querySelector("[data-checkout-btn]");

  if (subtotalEl) subtotalEl.textContent = "\u20b9" + subtotal.toFixed(0);
  if (deliveryEl) deliveryEl.textContent = "\u20b9" + deliveryFee.toFixed(0);
  if (totalEl) totalEl.textContent = "\u20b9" + total.toFixed(0);
  if (checkoutBtn) checkoutBtn.disabled = rows.length === 0;

  if (rows.length === 0 && !tbody.querySelector(".empty-cart")) {
    var cartSection = document.querySelector(".cart-section");
    var menuUrl = cartSection ? cartSection.getAttribute("data-menu-url") : "#";
    tbody.innerHTML =
      '<tr><td colspan="5"><div class="empty-cart">' +
      '<div class="empty-cart-icon">\ud83d\uded2</div>' +
      '<h3>Your cart is empty</h3>' +
      '<p>Looks like you haven\u2019t added anything yet. Explore our menu and find something delicious!</p>' +
      '<a href="' + menuUrl + '" class="primary-btn empty-cart-btn">Browse Menu \u2192</a>' +
      '<span class="empty-cart-note">Freshly prepared meals, just for you \u2764\ufe0f</span>' +
      '</div></td></tr>';
  }
}

// ============================================================
// Generic, reusable slider (Chef Special / Popular Dishes / Running
// Offers / Customer Reviews all use this same engine). One slide per
// view, automatic sliding, previous/next, dot indicators, and it
// pauses while the user is interacting (hover or touch).
// ============================================================
function initSliders() {
  document.querySelectorAll("[data-slider]").forEach(function (slider) {
    var track = slider.querySelector(".slider-track");
    if (!track) return;

    var slides = Array.prototype.slice.call(track.children);
    if (!slides.length) return;

    var dotsWrap = slider.querySelector(".slider-dots");
    var prevBtn = slider.querySelector(".slider-nav.prev");
    var nextBtn = slider.querySelector(".slider-nav.next");
    var autoplayMs = parseInt(slider.getAttribute("data-autoplay"), 10) || 0;
    var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var posterMode = slider.classList.contains("home-offers-slider") || slider.classList.contains("home-popular-slider");
    var index = 0;
    var timer = null;

    if (slides.length > 1 && dotsWrap) {
      slides.forEach(function (_, i) {
        var dot = document.createElement("button");
        dot.type = "button";
        dot.className = "slider-dot";
        dot.setAttribute("aria-label", "Go to slide " + (i + 1));
        dot.addEventListener("click", function () {
          goTo(i);
          restart();
        });
        dotsWrap.appendChild(dot);
      });
    }

    function updatePosterClasses() {
      slides.forEach(function (slide, i) {
        slide.classList.remove("is-current", "is-prev", "is-next", "is-hidden");
        if (slides.length === 1) {
          slide.classList.add("is-current");
          return;
        }

        if (i === index) {
          slide.classList.add("is-current");
        } else if (slides.length === 2) {
          // With two posters, keep the active poster centered and preview
          // the other poster on the right for a clean, uncluttered layout.
          slide.classList.add("is-next");
        } else if (i === (index - 1 + slides.length) % slides.length) {
          slide.classList.add("is-prev");
        } else if (i === (index + 1) % slides.length) {
          slide.classList.add("is-next");
        } else {
          slide.classList.add("is-hidden");
        }
      });
    }

    function update() {
      if (posterMode) {
        updatePosterClasses();
      } else {
        track.style.transform = "translate3d(-" + index * 100 + "%, 0, 0)";
      }

      if (dotsWrap) {
        Array.prototype.forEach.call(dotsWrap.children, function (dot, i) {
          dot.classList.toggle("active", i === index);
        });
      }
    }

    function goTo(i) {
      index = (i + slides.length) % slides.length;
      update();
    }

    function next() {
      goTo(index + 1);
    }

    function prev() {
      goTo(index - 1);
    }

    function start() {
      if (autoplayMs && slides.length > 1 && !timer && !reducedMotion) {
        timer = window.setInterval(next, autoplayMs);
      }
    }

    function stop() {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    }

    function restart() {
      stop();
      start();
    }

    if (prevBtn) {
      prevBtn.addEventListener("click", function () {
        prev();
        restart();
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener("click", function () {
        next();
        restart();
      });
    }

    slider.addEventListener("mouseenter", stop);
    slider.addEventListener("mouseleave", start);
    slider.addEventListener("touchstart", stop, { passive: true });
    slider.addEventListener("touchend", function () {
      window.setTimeout(start, 80);
    }, { passive: true });

    update();
    start();
  });
}

// ============================================================
// Password show/hide toggle (login + signup password fields)
// ============================================================
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".password-toggle").forEach(function (btn) {
    var input = document.getElementById(btn.getAttribute("data-target"));
    if (!input) return;
    btn.addEventListener("click", function () {
      var showing = input.type === "text";
      input.type = showing ? "password" : "text";
      btn.textContent = showing ? "Show" : "Hide";
      btn.setAttribute("aria-label", showing ? "Show password" : "Hide password");
    });
  });

  // Simple client-side "passwords match" hint on signup — purely a UX
  // nicety; the real check always happens on the server in the view.
  var pw1 = document.getElementById("id_password");
  var pw2 = document.getElementById("id_confirm_password");
  var matchNote = document.getElementById("password-match-note");
  if (pw1 && pw2 && matchNote) {
    var checkMatch = function () {
      if (!pw2.value) {
        matchNote.textContent = "";
        return;
      }
      matchNote.textContent = pw1.value === pw2.value ? "" : "Passwords do not match.";
    };
    pw1.addEventListener("input", checkMatch);
    pw2.addEventListener("input", checkMatch);
  }

  // Loading state on auth form submit buttons.
  document.querySelectorAll("form.auth-form").forEach(function (form) {
    form.addEventListener("submit", function () {
      var submitBtn = form.querySelector(".form-submit");
      if (submitBtn && !submitBtn.disabled) {
        submitBtn.disabled = true;
        submitBtn.classList.add("form-loading");
        submitBtn.dataset.originalText = submitBtn.textContent;
        submitBtn.textContent = "Please wait…";
      }
    });
  });
});
