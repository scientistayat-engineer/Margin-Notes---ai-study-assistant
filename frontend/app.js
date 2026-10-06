import {
  initializeApp
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";

import {
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  GoogleAuthProvider,
  signOut
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

import {
  getFirestore,
  doc,
  getDoc,
  setDoc
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js";

import * as cfg from "./firebase-config.js";

/* =========================================================
   CONFIG
========================================================= */

const firebaseConfig = cfg.firebaseConfig || {};

const isLocal =
  location.hostname === "localhost" ||
  location.hostname === "127.0.0.1";

const API = isLocal
  ? ""
  : String(cfg.API_BASE_URL || "").replace(/\/+$/, "");

const DEV =
  isLocal &&
  new URLSearchParams(location.search).has("dev");

/* =========================================================
   FIREBASE
========================================================= */

const fbApp = initializeApp(firebaseConfig);
const db = getFirestore(fbApp);
const realAuth = getAuth(fbApp);

const auth = DEV
  ? {
      currentUser: {
        email: "dev@localhost",
        uid: "dev",
        async getIdToken() {
          return "dev";
        }
      }
    }
  : realAuth;

/* =========================================================
   HELPERS
========================================================= */

const $ = (id) => document.getElementById(id);

let signup = false;
let hist = [];
let last = null;

const JSON_HEADERS = {
  "Content-Type": "application/json"
};

/* =========================================================
   HTML ESCAPE
========================================================= */

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"]/g,
    (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;"
    }[char])
  );
}

/* =========================================================
   MARKDOWN RENDERER
========================================================= */

function md(text) {
  let s = esc(text);

  /*
   * Code blocks
   */

  s = s.replace(
    /```(?:[a-zA-Z0-9_+-]+)?\n?([\s\S]*?)```/g,
    (_, code) => `<pre>${code.trim()}</pre>`
  );

  /*
   * Inline code
   */

  s = s.replace(
    /`([^`]+)`/g,
    "<code>$1</code>"
  );

  /*
   * Bold
   */

  s = s.replace(
    /\*\*([^*]+)\*\*/g,
    "<b>$1</b>"
  );

  /*
   * Headings
   */

  s = s.replace(
    /^### (.+)$/gm,
    "<h4>$1</h4>"
  );

  s = s.replace(
    /^## (.+)$/gm,
    "<h3>$1</h3>"
  );

  s = s.replace(
    /^# (.+)$/gm,
    "<h2>$1</h2>"
  );

  /*
   * Bullet points
   */

  s = s.replace(
    /^[*-] (.+)$/gm,
    "• $1"
  );

  /*
   * New lines
   */

  s = s.replace(/\n/g, "<br>");

  /*
   * Restore line breaks inside code blocks
   */

  s = s.replace(
    /<pre>([\s\S]*?)<\/pre>/g,
    (match) => match.replace(/<br>/g, "\n")
  );

  return s;
}

/* =========================================================
   THEME
========================================================= */

function setTheme(theme) {
  const root = document.documentElement;

  if (theme === "auto") {
    root.removeAttribute("data-theme");
  } else {
    root.dataset.theme = theme;
  }

  try {
    localStorage.setItem("theme", theme);
  } catch (_) {}

  document
    .querySelectorAll(".theme button")
    .forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.v === theme)
      );
    });
}

let savedTheme = "auto";

try {
  savedTheme =
    localStorage.getItem("theme") || "auto";
} catch (_) {}

document
  .querySelectorAll(".theme button")
  .forEach((button) => {
    button.onclick = () =>
      setTheme(button.dataset.v);
  });

setTheme(savedTheme);

/* =========================================================
   API AUTH TOKEN
========================================================= */

async function getAuthToken() {
  if (!auth.currentUser) {
    throw new Error(
      "Authentication required. Please log in first."
    );
  }

  return await auth.currentUser.getIdToken();
}

/* =========================================================
   NORMAL API REQUEST
========================================================= */

async function api(path, options = {}) {
  const token = await getAuthToken();

  const headers = {
    ...(options.headers || {}),
    Authorization: `Bearer ${token}`
  };

  /*
   * Don't force Content-Type for FormData.
   * Browser must create multipart boundary automatically.
   */

  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] =
      headers["Content-Type"] ||
      "application/json";
  }

  const response = await fetch(
    `${API}${path}`,
    {
      ...options,
      headers
    }
  );

  const contentType =
    response.headers.get("content-type") || "";

  let data;

  if (contentType.includes("application/json")) {
    data = await response.json();
  } else {
    const text = await response.text();

    try {
      data = JSON.parse(text);
    } catch (_) {
      data = {
        detail: text
      };
    }
  }

  if (!response.ok) {
    throw new Error(
      data?.detail ||
      data?.message ||
      "Something went wrong."
    );
  }

  return data;
}

/* =========================================================
   STREAMING ASK API
========================================================= */

/*
 * Backend response is:
 *
 * FIRST LINE:
 * {"sources":[...],"chunks":[...]}
 *
 * THEN:
 * Markdown answer
 *
 * So DON'T call response.json().
 * We read the stream manually.
 */

async function streamAsk(
  path,
  body,
  onMeta,
  onToken
) {
  const token = await getAuthToken();

  const response = await fetch(
    `${API}${path}`,
    {
      method: "POST",
      headers: {
        ...JSON_HEADERS,
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify(body)
    }
  );

  if (!response.ok) {
    const contentType =
      response.headers.get("content-type") || "";

    let errorData;

    if (contentType.includes("application/json")) {
      errorData = await response.json();
    } else {
      const text = await response.text();

      try {
        errorData = JSON.parse(text);
      } catch (_) {
        errorData = {
          detail: text
        };
      }
    }

    throw new Error(
      errorData?.detail ||
      errorData?.message ||
      "Request failed."
    );
  }

  if (!response.body) {
    throw new Error(
      "Streaming is not supported by this browser."
    );
  }

  const reader =
    response.body.getReader();

  const decoder =
    new TextDecoder("utf-8");

  let buffer = "";
  let metadataReceived = false;

  while (true) {
    const { done, value } =
      await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(
      value,
      { stream: true }
    );

    /*
     * First line contains JSON metadata.
     */

    if (!metadataReceived) {
      const newlineIndex =
        buffer.indexOf("\n");

      if (newlineIndex === -1) {
        continue;
      }

      const metadataText =
        buffer
          .slice(0, newlineIndex)
          .trim();

      buffer =
        buffer.slice(newlineIndex + 1);

      if (metadataText) {
        try {
          const metadata =
            JSON.parse(metadataText);

          onMeta(metadata);
        } catch (error) {
          console.error(
            "Metadata JSON error:",
            metadataText,
            error
          );

          throw new Error(
            "Invalid response metadata from server."
          );
        }
      }

      metadataReceived = true;
    }

    /*
     * Everything after the first line is
     * normal Markdown text.
     */

    if (metadataReceived && buffer) {
      onToken(buffer);
      buffer = "";
    }
  }

  /*
   * Flush remaining decoder data.
   */

  buffer += decoder.decode();

  if (metadataReceived && buffer) {
    onToken(buffer);
  }
}

/* =========================================================
   ERROR HANDLER
========================================================= */

function fail(error) {
  console.error(error);

  const element = $("err");

  if (!element) {
    alert(error.message);
    return;
  }

  element.textContent =
    error?.code
      ? error.code
          .replace("auth/", "")
          .replace(/-/g, " ")
      : error.message;
}

/* =========================================================
   LOGIN
========================================================= */

if ($("go")) {
  $("go").onclick = async () => {
    try {
      $("err").textContent = "";

      const email =
        $("em").value.trim();

      const password =
        $("pw").value;

      if (!email || !password) {
        throw new Error(
          "Please enter email and password."
        );
      }

      if (signup) {
        await createUserWithEmailAndPassword(
          auth,
          email,
          password
        );
      } else {
        await signInWithEmailAndPassword(
          auth,
          email,
          password
        );
      }
    } catch (error) {
      fail(error);
    }
  };
}

/* =========================================================
   GOOGLE LOGIN
========================================================= */

if ($("gg")) {
  $("gg").onclick = async () => {
    try {
      $("err").textContent = "";

      const provider =
        new GoogleAuthProvider();

      await signInWithPopup(
        auth,
        provider
      );
    } catch (error) {
      fail(error);
    }
  };
}

/* =========================================================
   LOGIN / SIGNUP SWITCH
========================================================= */

if ($("swap")) {
  $("swap").onclick = () => {
    signup = !signup;

    if ($("ft")) {
      $("ft").textContent =
        signup
          ? "Create account"
          : "Log in";
    }

    if ($("go")) {
      $("go").textContent =
        signup
          ? "Create account"
          : "Log in";
    }

    $("swap").textContent =
      signup
        ? "Have an account? Log in"
        : "New here? Create an account";
  };
}

/* =========================================================
   LOGOUT
========================================================= */

if ($("out")) {
  $("out").onclick = async () => {
    try {
      if (DEV) {
        location.assign("/");
      } else {
        await signOut(auth);
      }
    } catch (error) {
      fail(error);
    }
  };
}

/* =========================================================
   TABS
========================================================= */

document
  .querySelectorAll(".tab")
  .forEach((button) => {
    button.onclick = () => {
      document
        .querySelectorAll(".pane")
        .forEach((pane) => {
          pane.classList.add("hide");
        });

      const target =
        $("p-" + button.dataset.t);

      if (target) {
        target.classList.remove("hide");
      }

      document
        .querySelectorAll(".tab")
        .forEach((tab) => {
          tab.classList.toggle(
            "pri",
            tab === button
          );
        });

      if (button.dataset.t === "insp") {
        inspect();
      }
    };
  });

/* =========================================================
   DOCUMENT SHELF
========================================================= */

async function shelf() {
  const data =
    await api("/api/docs");

  if ($("shelf")) {
    $("shelf").innerHTML =
      data.files
        .map(
          (file) =>
            `<div class="book">${esc(file)}</div>`
        )
        .join("") ||
      `<div class="muted">No PDFs yet.</div>`;
  }

  if ($("cnt")) {
    $("cnt").textContent =
      `${data.chunks} chunks in vector DB`;
  }

  if ($("sf")) {
    $("sf").innerHTML =
      data.files
        .map(
          (file) =>
            `<option value="${esc(file)}">${esc(file)}</option>`
        )
        .join("");
  }
}

/* =========================================================
   SOURCE CHIPS
========================================================= */

function chips(sources) {
  if (
    !sources ||
    !sources.length
  ) {
    return "";
  }

  return `
    <div class="chips">
      ${sources
        .map(
          (source) => `
            <span
              class="chip"
              title="${esc(source.snippet || "")}"
            >
              ${esc(source.file)}
              · p.${esc(
                source.page ??
                source.chunk ??
                "—"
              )}
            </span>
          `
        )
        .join("")}
    </div>
  `;
}

/* =========================================================
   FINISH ASSISTANT MESSAGE
========================================================= */

function fin(element, text, sources) {
  element.innerHTML =
    md(text) +
    chips(sources) +
    `<button class="cp">Copy</button>`;

  const copyButton =
    element.querySelector(".cp");

  if (copyButton) {
    copyButton.onclick = async () => {
      try {
        await navigator.clipboard.writeText(
          text
        );

        copyButton.textContent =
          "Copied";
      } catch (_) {
        copyButton.textContent =
          "Copy failed";
      }
    };
  }
}

/* =========================================================
   CHAT BUBBLE
========================================================= */

function bubble(
  role,
  text = "",
  sources = []
) {
  const element =
    document.createElement("div");

  element.className =
    "msg " +
    (role === "user" ? "u" : "");

  if (role === "user") {
    element.textContent =
      text;
  } else if (text) {
    fin(
      element,
      text,
      sources
    );
  }

  if ($("chat")) {
    $("chat").appendChild(element);

    $("chat").scrollTop =
      $("chat").scrollHeight;
  }

  return element;
}

/* =========================================================
   SAVE CHAT
========================================================= */

async function save() {
  if (DEV) {
    return;
  }

  try {
    await setDoc(
      doc(
        db,
        "users",
        auth.currentUser.uid,
        "chat",
        "main"
      ),
      {
        messages:
          hist.slice(-40)
      }
    );
  } catch (error) {
    console.warn(
      "Chat save failed:",
      error
    );
  }
}

/* =========================================================
   AUTH STATE
========================================================= */

if (DEV) {
  $("login")?.classList.add("hide");
  $("app")?.classList.remove("hide");

  if ($("who")) {
    $("who").textContent =
      "dev@localhost";
  }

  shelf().catch(console.error);
} else {
  onAuthStateChanged(
    auth,
    async (user) => {
      if ($("login")) {
        $("login").classList.toggle(
          "hide",
          !!user
        );
      }

      if ($("app")) {
        $("app").classList.toggle(
          "hide",
          !user
        );
      }

      document
        .querySelectorAll(
          "#chat .msg:not(.welcome)"
        )
        .forEach(
          (node) => node.remove()
        );

      hist = [];
      last = null;

      if (!user) {
        return;
      }

      if ($("who")) {
        $("who").textContent =
          user.email || "User";
      }

      try {
        await shelf();
      } catch (error) {
        console.error(
          "Shelf loading failed:",
          error
        );
      }

      try {
        const snapshot =
          await getDoc(
            doc(
              db,
              "users",
              user.uid,
              "chat",
              "main"
            )
          );

        if (snapshot.exists()) {
          hist =
            snapshot.data().messages || [];

          if (
            hist.length &&
            $("sug")
          ) {
            $("sug").classList.add("hide");
          }

          hist.forEach(
            (message) => {
              bubble(
                message.role,
                message.content,
                message.sources || []
              );
            }
          );
        }
      } catch (error) {
        console.warn(
          "Chat history loading failed:",
          error
        );
      }
    }
  );
}

/* =========================================================
   PDF UPLOAD
========================================================= */

if ($("up")) {
  $("up").onclick = () => {
    $("file")?.click();
  };
}

if ($("file")) {
  $("file").onchange =
    async (event) => {
      const files =
        [...event.target.files];

      if (!files.length) {
        return;
      }

      const formData =
        new FormData();

      files.forEach(
        (file) => {
          formData.append(
            "files",
            file
          );
        }
      );

      if ($("cnt")) {
        $("cnt").textContent =
          "Creating embeddings…";
      }

      try {
        const result =
          await api(
            "/api/upload",
            {
              method: "POST",
              body: formData
            }
          );

        bubble(
          "assistant",
          `Indexed ${
            Object.keys(
              result.indexed || {}
            ).length
          } PDF(s) into ${
            result.chunks
          } chunks.`
        );

        await shelf();
      } catch (error) {
        bubble(
          "assistant",
          error.message
        );
      }

      event.target.value = "";
    };
}

/* =========================================================
   ASK QUESTION
========================================================= */

async function ask(question) {
  const q =
    question.trim();

  if (!q) {
    return;
  }

  if ($("sug")) {
    $("sug").classList.add("hide");
  }

  bubble(
    "user",
    q
  );

  if ($("q")) {
    $("q").value = "";
  }

  const answerBubble =
    bubble(
      "assistant",
      ""
    );

  answerBubble.classList.add(
    "dots"
  );

  let text = "";

  let metadata = {
    sources: [],
    chunks: []
  };

  try {
    await streamAsk(
      "/api/ask",
      {
        question: q,
        history:
          hist
            .slice(-6)
            .map(
              (message) => ({
                role:
                  message.role,
                content:
                  message.content
              })
            ),
        lang:
          $("lang")?.value || "en"
      },

      /*
       * METADATA
       */

      (meta) => {
        metadata = meta || {
          sources: [],
          chunks: []
        };

        answerBubble.classList.remove(
          "dots"
        );
      },

      /*
       * TOKENS
       */

      (token) => {
        text += token;

        /*
         * Render Markdown continuously.
         */

        answerBubble.innerHTML =
          md(text);

        if ($("chat")) {
          $("chat").scrollTop =
            $("chat").scrollHeight;
        }
      }
    );

    /*
     * Final rendering with sources + copy button.
     */

    fin(
      answerBubble,
      text,
      metadata.sources || []
    );

    hist.push(
      {
        role: "user",
        content: q
      },
      {
        role: "assistant",
        content: text,
        sources:
          metadata.sources || []
      }
    );

    last = metadata;

    await save();
  } catch (error) {
    console.error(
      "Ask error:",
      error
    );

    answerBubble.classList.remove(
      "dots"
    );

    answerBubble.textContent =
      error.message;
  }
}

/* =========================================================
   SEND BUTTON
========================================================= */

if ($("send")) {
  $("send").onclick = () =>
    ask(
      $("q")?.value || ""
    );
}

/* =========================================================
   ENTER KEY
========================================================= */

if ($("q")) {
  $("q").onkeydown = (event) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey
    ) {
      event.preventDefault();

      ask(
        $("q").value
      );
    }
  };
}

/* =========================================================
   PDF PRINT
========================================================= */

if ($("pdf")) {
  $("pdf").onclick = () =>
    window.print();
}

/* =========================================================
   VOICE INPUT
========================================================= */

if ($("mic")) {
  $("mic").onclick = () => {
    const Recognition =
      window.SpeechRecognition ||
      window.webkitSpeechRecognition;

    if (!Recognition) {
      alert(
        "Voice input works in Chrome or Edge."
      );

      return;
    }

    const recognition =
      new Recognition();

    recognition.lang =
      $("lang")?.value === "en"
        ? "en-US"
        : "ur-PK";

    recognition.onresult =
      (event) => {
        const transcript =
          event
            .results[0][0]
            .transcript;

        ask(transcript);
      };

    recognition.onerror =
      (event) => {
        console.error(
          "Speech recognition error:",
          event.error
        );
      };

    recognition.start();
  };
}

/* =========================================================
   SUGGESTIONS
========================================================= */

const suggestions = [
  "What are Python variables?",
  "List vs tuple?",
  "What is a for loop?",
  "How do functions work?",
  "What are conditional statements?"
];

if ($("sug")) {
  $("sug").innerHTML =
    suggestions
      .map(
        (text) =>
          `<button>${esc(text)}</button>`
      )
      .join("");

  $("sug").onclick =
    (event) => {
      if (
        event.target.tagName ===
        "BUTTON"
      ) {
        ask(
          event.target.textContent
        );
      }
    };
}

/* =========================================================
   QUIZ
========================================================= */

let Qs = [];
let qi = 0;
let sc = 0;

if ($("qstart")) {
  $("qstart").onclick =
    async () => {
      if ($("qbox")) {
        $("qbox").textContent =
          "Writing questions from your chapters…";
      }

      try {
        const result =
          await api(
            "/api/quiz",
            {
              method: "POST",
              headers:
                JSON_HEADERS,
              body:
                JSON.stringify({
                  n: 5,
                  lang:
                    $("lang")?.value ||
                    "en"
                })
            }
          );

        Qs =
          result.questions || [];

        qi = 0;
        sc = 0;

        showQ();
      } catch (error) {
        if ($("qbox")) {
          $("qbox").textContent =
            error.message;
        }
      }
    };
}

/* =========================================================
   SHOW QUIZ QUESTION
========================================================= */

function showQ() {
  if (!$("qbox")) {
    return;
  }

  if (qi >= Qs.length) {
    $("qbox").innerHTML = `
      <div class="msg">
        <b>
          Score: ${sc} / ${Qs.length}
        </b>
      </div>
    `;

    return;
  }

  const q =
    Qs[qi];

  $("qbox").innerHTML = `
    <div class="msg">
      <b>
        ${qi + 1}/${Qs.length}.
        ${esc(q.q)}
      </b>

      <div class="opts">
        ${q.options
          .map(
            (option, index) => `
              <button
                data-i="${index}"
              >
                ${esc(option)}
              </button>
            `
          )
          .join("")}
      </div>

      <div id="why"></div>
    </div>
  `;

  $("qbox")
    .querySelectorAll(
      ".opts button"
    )
    .forEach(
      (button) => {
        button.onclick = () => {
          const correct =
            Number(
              button.dataset.i
            ) ===
            Number(q.answer);

          if (correct) {
            sc++;
          }

          $("qbox")
            .querySelectorAll(
              ".opts button"
            )
            .forEach(
              (other) => {
                other.disabled =
                  true;

                if (
                  Number(
                    other.dataset.i
                  ) ===
                  Number(q.answer)
                ) {
                  other.classList.add(
                    "ok"
                  );
                }
              }
            );

          if (!correct) {
            button.classList.add(
              "bad"
            );
          }

          const why =
            $("why");

          if (why) {
            why.innerHTML = `
              <p>
                ${esc(q.why || "")}
              </p>

              <button
                class="pri"
                id="nx"
              >
                ${
                  qi + 1 < Qs.length
                    ? "Next question"
                    : "See score"
                }
              </button>
            `;

            $("nx").onclick =
              () => {
                qi++;
                showQ();
              };
          }
        };
      }
    );
}

/* =========================================================
   RAG INSPECTOR
========================================================= */

async function inspect() {
  if (!$("insp")) {
    return;
  }

  $("insp").textContent =
    "Loading…";

  try {
    const data =
      await api(
        "/api/inspect"
      );

    const perFile =
      data.per_file || {};

    const max =
      Math.max(
        1,
        ...Object.values(perFile)
      );

    $("insp").innerHTML = `
      <h2>RAG Inspector</h2>

      <div class="grid">
        <div class="stat">
          <b>${data.chunks}</b>
          chunks stored
        </div>

        <div class="stat">
          <b>${data.dim}</b>
          embedding dimensions
        </div>

        <div class="stat">
          <b>${Object.keys(perFile).length}</b>
          PDFs indexed
        </div>
      </div>

      <p class="muted">
        ${esc(data.model || "")}
        ·
        ${esc(data.store || "")}
        ·
        chunk ${data.chunk_size}
        chars,
        overlap ${data.overlap}
      </p>

      <h3>
        Chunks per PDF
      </h3>

      ${Object.entries(perFile)
        .map(
          ([file, count]) => `
            <div class="bar">
              <span>
                ${esc(file)}
              </span>

              <i
                style="
                  width:${Math.max(
                    4,
                    (count / max) * 100
                  )}%
                "
              ></i>

              <em>
                ${count}
              </em>
            </div>
          `
        )
        .join("")}

      <h3>
        Sample embeddings
      </h3>

      ${(data.samples || [])
        .map(
          (sample) => `
            <div class="msg">
              <code>
                ${esc(sample.id)}
              </code>

              <div class="muted">
                ${esc(sample.text)}…
              </div>

              <code>
                [
                ${(sample.vec || []).join(", ")}
                , …
                ]
              </code>
            </div>
          `
        )
        .join("")}

      <h3>
        Last question: retrieved chunks
      </h3>

      ${
        last?.chunks?.length
          ? `
            <table>
              <tr>
                <th>Score</th>
                <th>Source</th>
                <th>Text</th>
              </tr>

              ${last.chunks
                .map(
                  (chunk, index) => {
                    const source =
                      (last.sources || [])[index] || {};

                    const distance =
                      source.distance;

                    const score =
                      distance != null &&
                      Number.isFinite(
                        Number(distance)
                      )
                        ? Number(distance).toFixed(4)
                        : "—";

                    const sourceFile =
                      source.file ||
                      "unknown.pdf";

                    const sourceChunk =
                      source.chunk ??
                      source.page ??
                      index;

                    return `
                      <tr>
                        <td>
                          ${esc(score)}
                        </td>

                        <td>
                          ${esc(sourceFile)}
                          · chunk ${esc(sourceChunk)}
                        </td>

                        <td>
                          ${esc(
                            String(chunk || "")
                          ).slice(0, 300)}…
                        </td>
                      </tr>
                    `;
                  }
                )
                .join("")}
            </table>
          `
          : `
            <p class="muted">
              Ask a question in Chat first.
            </p>
          `
      }
    `;
  } catch (error) {
    $("insp").textContent =
      error.message;
  }
}

/* =========================================================
   STUDY MODE
========================================================= */

async function study(mode) {
  if (!$("sbox")) {
    return;
  }

  $("sbox").textContent =
    "Working on it…";

  try {
    const result =
      await api(
        "/api/study",
        {
          method: "POST",
          headers:
            JSON_HEADERS,

          body:
            JSON.stringify({
              file:
                $("sf")?.value || "",

              mode,

              lang:
                $("lang")?.value ||
                "en"
            })
        }
      );

    if (mode === "summary") {
      $("sbox").innerHTML =
        `
          <div class="msg">
            ${md(result.text || "")}
          </div>
        `;

      return;
    }

    const cards =
      result.cards || [];

    $("sbox").innerHTML = `
      <div class="grid">
        ${cards
          .map(
            (card) => `
              <div
                class="stat card"
                tabindex="0"
                role="button"
              >
                <span>
                  ${esc(card.front)}
                </span>

                <span class="hide">
                  ${esc(card.back)}
                </span>
              </div>
            `
          )
          .join("")}
      </div>
    `;

    $("sbox")
      .querySelectorAll(".card")
      .forEach(
        (card) => {
          const flip = () => {
            card
              .querySelectorAll("span")
              .forEach(
                (span) =>
                  span.classList.toggle(
                    "hide"
                  )
              );
          };

          card.onclick = flip;

          card.onkeydown =
            (event) => {
              if (
                event.key ===
                "Enter"
              ) {
                flip();
              }
            };
        }
      );
  } catch (error) {
    $("sbox").textContent =
      error.message;
  }
}

if ($("sum")) {
  $("sum").onclick =
    () => study("summary");
}

if ($("fc")) {
  $("fc").onclick =
    () => study("flashcards");
}

/* =========================================================
   EVALUATION
========================================================= */

if ($("ev")) {
  $("ev").onclick =
    async () => {
      if ($("evo")) {
        $("evo").textContent =
          "Running 10 questions…";
      }

      try {
        const data =
          await api(
            "/api/eval"
          );

        /*
         * Backend returns hit1/hit5 as
         * decimal fractions:
         *
         * 0.9 -> 90%
         * 1.0 -> 100%
         */

        const hit1 =
          Number(data.hit1 || 0) * 100;

        const hit5 =
          Number(data.hit5 || 0) * 100;

        $("evo").innerHTML = `
          <div class="grid">
            <div class="stat">
              <b>
                ${hit1.toFixed(0)}%
              </b>
              right PDF ranked first
            </div>

            <div class="stat">
              <b>
                ${hit5.toFixed(0)}%
              </b>
              right PDF in top 5
            </div>

            <div class="stat">
              <b>
                ${data.mrr}
              </b>
              mean reciprocal rank
            </div>
          </div>

          <table>
            <tr>
              <th>Question</th>
              <th>Expected PDF</th>
              <th>Rank</th>
            </tr>

            ${(data.rows || [])
              .map(
                (row) => `
                  <tr>
                    <td>
                      ${esc(
                        row.q ||
                        row.question ||
                        ""
                      )}
                    </td>

                    <td>
                      ${esc(
                        row.expected ||
                        ""
                      )}
                    </td>

                    <td>
                      ${
                        row.rank ??
                        "miss"
                      }
                    </td>
                  </tr>
                `
              )
              .join("")}
          </table>
        `;
      } catch (error) {
        if ($("evo")) {
          $("evo").textContent =
            error.message;
        }
      }
    };
}

/* =========================================================
   INITIAL MESSAGE
========================================================= */

console.log(
  "AI Study Assistant frontend loaded."
);

console.log(
  "API:",
  API || "(same origin)"
);

console.log(
  "DEV mode:",
  DEV
);
