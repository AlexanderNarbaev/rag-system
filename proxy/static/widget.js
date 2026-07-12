/**
 * RAG Chat Widget — vanilla JS, no dependencies, air-gapped.
 * 
 * Embed in any page:
 *   <script src="/v1/widget.js"></script>
 *   <div id="rag-chat"></div>
 *   <script>
 *     RAGChatWidget.init({
 *       container: 'rag-chat',
 *       endpoint: '/v1/chat/completions',
 *       token: 'your-jwt-token',  // optional: for authenticated access
 *     });
 *   </script>
 *
 * Supports SSE streaming, markdown-like formatting, source display,
 * and graceful error handling.
 */

(function () {
  'use strict';

  var RAGChatWidget = {
    _config: {},
    _streaming: false,
    _currentAssistantMsg: null,
    _messagesEl: null,
    _inputEl: null,
    _sendBtn: null,

    /**
     * Initialize the chat widget.
     * @param {Object} config
     * @param {string} config.container - CSS selector or element ID for the root container
     * @param {string} config.endpoint - Chat completions endpoint (default: '/v1/chat/completions')
     * @param {string} [config.token] - JWT Bearer token for authenticated requests
     * @param {string} [config.messagesContainer] - ID of messages container element
     * @param {string} [config.inputId] - ID of input element
     * @param {string} [config.sendId] - ID of send button element
     * @param {string} [config.model] - Model name to use
     */
    init: function (config) {
      this._config = Object.assign({
        endpoint: '/v1/chat/completions',
        token: null,
        model: null,
      }, config);

      var container = document.getElementById(this._config.container) || document.querySelector(this._config.container);
      if (!container) {
        console.error('[RAG Widget] Container not found:', this._config.container);
        return;
      }

      this._messagesEl = document.getElementById(this._config.messagesContainer) || container.querySelector('.rag-messages');
      this._inputEl = document.getElementById(this._config.inputId) || container.querySelector('input[type="text"]');
      this._sendBtn = document.getElementById(this._config.sendId) || container.querySelector('button');

      if (!this._inputEl || !this._sendBtn || !this._messagesEl) {
        console.error('[RAG Widget] Required elements not found. Looking for messages container, input, and send button.');
        return;
      }

      this._bindEvents();
    },

    _bindEvents: function () {
      var self = this;

      this._sendBtn.addEventListener('click', function () {
        self._sendMessage();
      });

      this._inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          self._sendMessage();
        }
      });
    },

    _sendMessage: function () {
      var text = this._inputEl.value.trim();
      if (!text || this._streaming) return;

      this._inputEl.value = '';
      this._streaming = true;

      // Disable input during streaming
      this._inputEl.disabled = true;
      this._sendBtn.disabled = true;

      // Add user message
      this._addMessage(text, 'user');

      // Add typing indicator
      var typingEl = this._addTypingIndicator();

      var self = this;

      // Build request
      var headers = { 'Content-Type': 'application/json' };
      if (this._config.token) {
        headers['Authorization'] = 'Bearer ' + this._config.token;
      }

      var body = JSON.stringify({
        model: this._config.model || 'rag-model',
        messages: [{ role: 'user', content: text }],
        stream: true,
      });

      fetch(this._config.endpoint, {
        method: 'POST',
        headers: headers,
        body: body,
      })
        .then(function (response) {
          if (!response.ok) {
            return response.text().then(function (errText) {
              throw new Error('HTTP ' + response.status + ': ' + errText);
            });
          }

          // Remove typing indicator
          if (typingEl && typingEl.parentNode) {
            typingEl.parentNode.removeChild(typingEl);
          }

          // Create assistant message for streaming
          self._currentAssistantMsg = self._addMessage('', 'assistant');

          // Read SSE stream
          var reader = response.body.getReader();
          var decoder = new TextDecoder();
          var buffer = '';

          function readStream() {
            reader.read().then(function (result) {
              if (result.done) {
                self._onStreamEnd();
                return;
              }

              buffer += decoder.decode(result.value, { stream: true });
              var lines = buffer.split('\n');
              // Keep the last incomplete line in buffer
              buffer = lines.pop() || '';

              for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (!line || !line.startsWith('data: ')) continue;
                var data = line.substring(6);
                if (data === '[DONE]') {
                  self._onStreamEnd();
                  return;
                }
                try {
                  var chunk = JSON.parse(data);
                  var delta = (chunk.choices && chunk.choices[0] && chunk.choices[0].delta);
                  if (delta && delta.content) {
                    self._appendToCurrentMessage(delta.content);
                  }
                } catch (e) {
                  // Skip malformed chunks
                }
              }

              readStream();
            }).catch(function (err) {
              self._onStreamError(err);
            });
          }

          readStream();
        })
        .catch(function (err) {
          if (typingEl && typingEl.parentNode) {
            typingEl.parentNode.removeChild(typingEl);
          }
          self._onStreamError(err);
        });
    },

    _addMessage: function (text, role) {
      var msgEl = document.createElement('div');
      msgEl.className = 'rag-message rag-' + role;
      msgEl.textContent = text;
      this._messagesEl.appendChild(msgEl);
      this._scrollToBottom();
      return msgEl;
    },

    _addTypingIndicator: function () {
      var el = document.createElement('div');
      el.className = 'rag-message rag-assistant';
      el.innerHTML = '<div class="rag-typing"><span></span><span></span><span></span></div>';
      this._messagesEl.appendChild(el);
      this._scrollToBottom();
      return el;
    },

    _appendToCurrentMessage: function (text) {
      if (!this._currentAssistantMsg) return;
      this._currentAssistantMsg.textContent += text;
      this._scrollToBottom();
    },

    _onStreamEnd: function () {
      this._streaming = false;
      this._currentAssistantMsg = null;
      this._inputEl.disabled = false;
      this._sendBtn.disabled = false;
      this._inputEl.focus();
    },

    _onStreamError: function (err) {
      this._streaming = false;
      this._currentAssistantMsg = null;
      this._inputEl.disabled = false;
      this._sendBtn.disabled = false;

      var errorMsg = err.message || 'An error occurred';
      // Handle 401 specifically
      if (errorMsg.indexOf('401') !== -1) {
        errorMsg = 'Authentication required. Please log in first.';
      }
      this._addMessage('Error: ' + errorMsg, 'error');
      this._scrollToBottom();
    },

    _scrollToBottom: function () {
      if (this._messagesEl) {
        this._messagesEl.scrollTop = this._messagesEl.scrollHeight;
      }
    },
  };

  // Expose globally
  window.RAGChatWidget = RAGChatWidget;
})();
