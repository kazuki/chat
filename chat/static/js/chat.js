(function(global) {
    Number.prototype.padding2 = function() {
        return ("00"+this).slice(-2);
    };
    Date.prototype.toString = function() {
        return (this.getMonth() + 1).padding2() + "/"
            + this.getDate().padding2()
            + "[" + "日月火水木金土".charAt(this.getDay()) + "]" + " "
            + this.getHours().padding2() + ":"
            + this.getMinutes().padding2() + ":"
            + this.getSeconds().padding2();
    };

    var ws_server_url = (window.location.protocol === 'http:' ? 'ws://' : 'wss://')
        + window.location.host
        + window.location.pathname.substr(0, window.location.pathname.lastIndexOf('/'))
        + '/ws';
    var config_ = global.Config || {};
    var config_linkmap_ = config_.LinkMap || [];
    var config_replaces_ = config_.Replaces || [];
    $.support.noreferrer = $.support.noreferrer || (function() {
        return window.navigator.userAgent.indexOf('AppleWebKit') != -1;
    })();

    if (!window.WebSocket || !window.localStorage) {
        window.location.replace("lite"); // lite版へリダイレクト
        return;
    }

    var MessagingSocket = function(remote_endpoint) {
        var self = this;
        this.sock_ = new WebSocket(remote_endpoint);
        this.keepAliveTime = 30;
        this.ephemeral_ = 0;
        this.callbacks_ = {};
        this.onopen = function() {};
        this.onclose = function() {};
        this.onmessage = function(ev) {};
        this.sock_.onopen = function() {
            self.sock_.send(JSON.stringify({
                'm': 'auth',
                'user-id': WebSocketAuthUserID,
                'nonce': WebSocketAuthNonce,
                'token': WebSocketAuthToken
            }));
            self.last_ = Date.now();
            self.timer_ = window.setInterval(self.elapsed_, 10000);
            self.onopen();
        };
        this.sock_.onclose = function() {
            // TODO: 応答待ちのコールバックをすべて発火
            if (self.timer_) window.clearInterval(self.timer_);
            self.onclose();
        };
        this.sock_.onmessage = function(ev) {
            self.last_ = Date.now();
            if (typeof ev.data === 'string' && ev.data[0] === '{') {
                try {
                    json = JSON.parse(ev.data);
                    if ('e' in json && json['e'] in self.callbacks_) {
                        entry = self.callbacks_[json['e']];
                        delete self.callbacks_[json['e']];
                        try {
                            entry[1](json);
                        } catch (e) {}
                        return;
                    }
                    self.onmessage(json);
                } catch (e) {}
            }
        };
        this.elapsed_ = function() {
            // TODO: 応答待ちタイムアウト確認
            if ((Date.now() - self.last_) >= self.keepAliveTime * 1000) {
                self.send({'m':'ping'}, function(response){
                    if (!response)
                        console.log('websocket disconnected');
                });
            }
        };
        this.send = function(msg, callback) {
            var key = ++self.ephemeral_;
            msg['e'] = key;
            self.callbacks_[key] = [Date.now(), callback];
            self.sock_.send(JSON.stringify(msg));
            self.last_ = Date.now();
        };
    };

    $(function() {
        /* 初期値 */
        var DEFAULT_NAME = config_.DefaultName || "名無し"; // 名前の初期値
        var DEFAULT_COLOR = config_.DefaultColor || "black"; // 色の初期値
        var DEFAULT_ICON_URL = config_.DefaultIcon || "img/no-image.min.svg"; // アイコン初期URL
        var DEFAULT_IMAGE_HASH_URL = config_.DefaultImageHashUrl || "hash/";
        var DEFAULT_ICON_SIZE = config_.DefaultIconSize || 1.2;
        var DEFAULT_MSG_COUNT = config_.DefaultMsgCount || 50;

        /* 状態保持変数 */
        var latest_id_ = -1; // 受信した最新メッセージID
        var sock_ = null;    // WebSocket
        var counter_ = 0;    // 重複排除用のユニークID生成用カウンタ
        var regex_ = /(?:https?|ftp):\/\/([a-zA-Z0-9$-_\.\+\!\~\*\'\(\),%?\/;:@&=#]+)/;
        var title_ = config_.Title || 'チャット';
        var unread_ = 0;
        var inactive_ = false;
        var icon_max_size_ = null;

        /* localStorage キー */
        var LOCALSTORAGE_NAME = "name";
        var LOCALSTORAGE_COLOR = "color";
        var LOCALSTORAGE_ICON = "icon";
        var LOCALSTORAGE_ICON_SIZE = "icon-size";
        var LOCALSTORAGE_SHOW_MY_ICON = 'show-my-icon';
        var LOCALSTORAGE_MSG_COUNT = 'msg-count';
        var LOCALSTORAGE_FONTS = 'fonts';
        var LOCALSTORAGE_FONT_SIZE = 'font-size';
        var fetch_localstorage_name = function() { return localStorage.getItem(LOCALSTORAGE_NAME) || DEFAULT_NAME; };
        var fetch_localstorage_color = function() { return localStorage.getItem(LOCALSTORAGE_COLOR) || DEFAULT_COLOR; };
        var fetch_localstorage_icon = function() { return localStorage.getItem(LOCALSTORAGE_ICON) ? DEFAULT_IMAGE_HASH_URL + localStorage.getItem(LOCALSTORAGE_ICON) : DEFAULT_ICON_URL; };
        var fetch_localstorage_icon_size = function() { return parseFloat(localStorage.getItem(LOCALSTORAGE_ICON_SIZE) || DEFAULT_ICON_SIZE); };
        var fetch_localstorage_show_my_icon = function() { return (localStorage.getItem(LOCALSTORAGE_SHOW_MY_ICON) || 'true') == 'true'; };
        var fetch_localstorage_msg_count = function() { return parseFloat(localStorage.getItem(LOCALSTORAGE_MSG_COUNT) || DEFAULT_MSG_COUNT); };
        var fetch_localstorage_fonts = function() { return localStorage.getItem(LOCALSTORAGE_FONTS) || ''; };
        var fetch_localstorage_font_size = function() { return parseFloat(localStorage.getItem(LOCALSTORAGE_FONT_SIZE) || 1.0); };

        var max_view_messages_ = fetch_localstorage_msg_count(); // 最大表示チャットログ行数

        /* HTMLノード保持変数 */
        var msg_container = $('#msg_container');
        var post_container = $('#post_container');
        var ws_status = $(document.createElement('div')).appendTo($(document.body)).attr('id', 'ws_status').addClass('ui-widget-overlay').css('display','none');
        var ws_status_msg = function() {
            var tmp = $(document.createElement('div')).appendTo($(document.body)).attr('id', 'ws_status_msg').addClass('ui-widget').css('display','none');
            $(document.createElement('div')).appendTo(tmp).addClass('ui-state-error').addClass('ui-corner-all')
                .html('<div><span class="ui-icon ui-icon-alert" style="float:left;margin-right:.3em;"></span>Disconnected WebSocket...</div>');
            return tmp;
        } ();
        var post_button = $('#post_button');
        var msg_field   = $('#msg_field');
        var config_dialog = $('#config_dialog');

        /* UIセットアップ */
        document.title = title_;
        $(window).blur(function() {
            inactive_ = true;
        });
        $(window).focus(function() {
            inactive_ = false;
            if (unread_ != 0) {
                unread_ = 0;
                document.title = title_;
            }
        });
        $('#profile_icon')
            .css('max-height', fetch_localstorage_icon_size() + 'em').css('max-width', fetch_localstorage_icon_size() + 'em')
            .css('display', fetch_localstorage_show_my_icon() ? 'inline' : 'none');
        $('#post_button').button({icons:{primary:'ui-icon-comment'},text:false});
        $('#config_button').button({icons:{primary:'ui-icon-gear'},text:false}).click(function(){$('#config_dialog').dialog('open');});
        $('#config_dialog').dialog({
            autoOpen: false,
            modal: true,
            width: 'auto',
            open: function(event, ui) {
                $('#config_name').val(fetch_localstorage_name());
                $('#config_color').val(fetch_localstorage_color());
                $('#config_icon_preview').attr('src', fetch_localstorage_icon());
                $('#config_show_my_icon').prop('checked',fetch_localstorage_show_my_icon());
                $('#config_icon_size').spinner('value', fetch_localstorage_icon_size());
                $('#config_msg_count').spinner('value', fetch_localstorage_msg_count());
                $('#config_font').val(fetch_localstorage_fonts());
                $('#config_font_size').spinner('value', fetch_localstorage_font_size());
            },
            buttons: {
                'Save': function() {
                    localStorage.setItem(LOCALSTORAGE_NAME, $('#config_name').val());
                    localStorage.setItem(LOCALSTORAGE_COLOR, $('#config_color').val());
                    localStorage.setItem(LOCALSTORAGE_SHOW_MY_ICON, $('#config_show_my_icon').prop('checked') ? 'true' : 'false');
                    if (!isNaN(parseFloat($('#config_font_size').val())))
                        localStorage.setItem(LOCALSTORAGE_FONT_SIZE, parseFloat($('#config_font_size').val() + ''));
                    localStorage.setItem(LOCALSTORAGE_FONTS, $('#config_font').val());
                    var new_icon = $('#config_icon_preview').attr('src');
                    if (new_icon.substr(0, 11) === 'data:image/') {
                        var pos1 = new_icon.indexOf(',');
                        var pos2 = new_icon.indexOf(';');
                        if (pos2 < 0) pos2 = pos1;
                        var mime_type = new_icon.substring(5, pos2);
                        var icon_data = new_icon.substr(pos1 + 1);

                        var prog_dlg = $(document.createElement('div'))
                            .appendTo($(document.body)).dialog({modal:true,height:'auto'});
                        $(document.createElement('p')).text('Uploading image...').appendTo(prog_dlg);
                        var prog = $(document.createElement('div')).progressbar({value:false}).appendTo(prog_dlg);
                        sock_.send({
                            'm': 'store-icon',
                            't': mime_type,
                            'd': icon_data
                        }, function(ev) {
                            prog_dlg.dialog('destroy');
                            prog_dlg.detach();
                            if (!ev || ev.r != 'ok') { alert('icon upload error. please reload page'); return; }
                            localStorage.setItem(LOCALSTORAGE_ICON, ev.h);
                            $('#profile_icon').attr('src', fetch_localstorage_icon());
                        });
                    }
                    $('#profile_icon').css('display', fetch_localstorage_show_my_icon() ? 'inline' : 'none');
                    if (fetch_localstorage_icon_size() != parseFloat($('#config_icon_size').val())) {
                        var size = parseFloat($('#config_icon_size').val()) + '';
                        localStorage.setItem(LOCALSTORAGE_ICON_SIZE, size);
                        if (size == '0') {
                            $('#msg_container img').css('display', 'none');
                            $('#profile_icon').css('display', 'none');
                        } else {
                            size += 'em';
                            $('#msg_container img').css('max-height', size).css('max-width', size).css('display', 'inline');
                            $('#profile_icon').css('max-height', size).css('max-width', size)
                                .css('display', fetch_localstorage_show_my_icon() ? 'inline' : 'none');
                        }
                    }
                    if (fetch_localstorage_msg_count() != parseInt($('#config_msg_count').val())) {
                        req_fetch = (max_view_messages_ < parseInt($('#config_msg_count').val()));
                        max_view_messages_ = parseInt($('#config_msg_count').val());
                        localStorage.setItem(LOCALSTORAGE_MSG_COUNT, max_view_messages_ + '');
                        if (req_fetch) {
                            latest_id_ = -1;
                            sock_.onopen();
                        } else {
                            remove_messages();
                        }
                    }
                    apply_fonts_and_icon_size();
                    $(window).resize();
                    $(this).dialog("close");
                },
                'Cancel': function() {
                    $(this).dialog("close");
                }
            }
        });
        $('#open_icon_file_button').button({icons:{primary:"ui-icon-folder-open"},text:false});
        $('#choose_icon_button').button({icons:{primary:"ui-icon-image"},text:false}).click(function() {
            alert('未実装！すでにサーバサイドにアップロード済みのアイコン一覧から選択する機能を実装する...予定');
        });
        $('#config_icon_size').spinner({step:0.1,min:0,max:10});
        $('#config_msg_count').spinner({step:1,min:1,max:10000});
        $('#config_font_size').spinner({step:0.1,min:0.1,max:10});
        var apply_fonts_and_icon_size = function() {
            $('#post_container').css('font-size', fetch_localstorage_font_size() + 'em')
                .css('font-family', fetch_localstorage_fonts());
            $('#msg_container').css('font-size', fetch_localstorage_font_size() + 'em')
                .css('font-family', fetch_localstorage_fonts());

            // emからpxサイズを取得 (他にいい方法あればいいな...)
            var tmp = $(document.createElement('div')).css('font-size', fetch_localstorage_icon_size() + 'em')
                .css('display', 'none').text('Aa').appendTo($(document.body))
            icon_max_size_ = tmp.height();
            tmp.detach();

            $('#profile_icon').attr('src', fetch_localstorage_icon() + '?s=' + icon_max_size_)
            msg_container.find('img').each(function(idx, img) {
                var url = img.src;
                if (url.indexOf('?') > 0)
                    url = url.substring(0, url.indexOf('?'));
                img.src = url + '?s=' + icon_max_size_;
            });
        };
        apply_fonts_and_icon_size ();

        var change_ws_status = function(is_connected) {
            post_button.button({disabled: !is_connected});
            if (is_connected) {
                ws_status.css('display', 'none');
                ws_status_msg.css('display', 'none');
            } else {
                $(window).resize();
                ws_status.css('display', 'block');
                ws_status_msg.css('display', 'block');
            }
        };
        var remove_messages = function() {
            while (msg_container.children().size() > max_view_messages_)
                msg_container.children().last().detach();
        };
        var append_txt = function(ele, txt) {
            var try_decode_uri = function(encoded_uri) {
                try {
                    return decodeURIComponent(encoded_uri);
                } catch (e) {
                    return encoded_uri;
                }
            };
            var create_link_element = function (url, text) {
                var e = $(document.createElement ('a'));
                if ($.support.noreferrer) {
                    e.attr('rel', 'noreferrer');
                    e.attr('href', url);
                    e.attr('target', '_blank');
                } else {
                    e.click(function () {
                        w = window.open ();
                        w.document.write ('<meta http-equiv="refresh" content="0;url=' + url + '">');
                        w.document.close ();
                        return false;
                    });
                    e.attr('href', url);
                }
                return e.text(text);
            };
            while (txt.length > 0) {
                var tmp = txt.match(regex_);
                if (!tmp) {
                    ele.append ($(document.createTextNode (txt)));
                    return;
                }
                var url = tmp[0], suffix = tmp[1], lnk_text = try_decode_uri(tmp[0]);
                for (var i = 0; i < config_linkmap_.length; ++i) {
                    var map_entry = config_linkmap_[i];
                    if (suffix.length < map_entry[0].length) continue;
                    if (suffix.substr(0, map_entry[0].length) === map_entry[0]) {
                        lnk_text = map_entry[1] + ":" + try_decode_uri(suffix.substr(map_entry[0].length));
                        break;
                    }
                }
                ele.append ($(document.createTextNode (RegExp.leftContext)))
                    .append(create_link_element(url, lnk_text));
                txt = RegExp.rightContext;
            }
        };
        var append_msg = function(msg) {
            if (latest_id_ < msg.i) latest_id_ = msg.i;
            var e0 = $(document.createElement('div'))
                .addClass('ui-widget-content').addClass('message-content');
            var dt = new Date(msg.d);
            msg.g = (msg.g ? DEFAULT_IMAGE_HASH_URL + msg.g : DEFAULT_ICON_URL);
            img = $(document.createElement('img')).attr('src', msg.g + '?s=' + icon_max_size_)
                .css('max-height', fetch_localstorage_icon_size() + 'em').css('max-width', fetch_localstorage_icon_size() + 'em')
                .appendTo(e0);
            if (fetch_localstorage_icon_size() + '' == '0') img.css('display', 'none');
            txt = $(document.createElement('div')).css('color', msg.c)
                .append($(document.createTextNode(msg.n + "> ")));
            config_replaces_.forEach(function(entry) {
                msg.t = msg.t.replace(entry[0], entry[1]);
            });
            append_txt(txt, msg.t);
            txt.append($(document.createTextNode(" (" + dt.toString() + ")")));
            txt.appendTo(e0);
            if (msg_container.children().size() == 0) {
                e0.appendTo(msg_container);
            } else {
                e0.insertBefore(msg_container.children(':first-child'));
            }

            remove_messages();

            if (inactive_) {
                unread_ ++;
                document.title = '[' + unread_ + '] ' + title_;
            }
        };
        var open_socket = function() {
            sock_ = new MessagingSocket(ws_server_url);
            sock_.onopen = function() {
                change_ws_status(true);
                sock_.send({
                    'm': 'latest', 'c': max_view_messages_, 'i': latest_id_
                }, function(ev) {
                    if (!ev || ev.r != 'ok') return;
                    ev.m = ev.m.reverse();
                    for (var i in ev.m) append_msg(ev.m[i]);
                });
            };
            sock_.onmessage = function(ev) {
                if ('m' in ev) {
                    if (ev.m === 'strm') {
                        append_msg(ev.d);
                        return;
                    }
                }
                console.log(ev);
            };
            sock_.onclose = function() {
                change_ws_status(false);
                window.setTimeout(function() {
                    open_socket();
                }, 1000);
            };
        };

        post_button.click(function() {
            if (msg_field.val().length === 0) return;
            post_button.button({disabled:true});
            sock_.send({
                'm': 'post',
                'n': fetch_localstorage_name(),
                'c': fetch_localstorage_color(),
                'g': fetch_localstorage_icon() === DEFAULT_ICON_URL ? null : fetch_localstorage_icon().substr(DEFAULT_IMAGE_HASH_URL.length),
                't': msg_field.val(),
                'r': Date.now().toString(16) + ":" + (counter_++).toString(16)
            }, function(ev) {
                post_button.button({disabled:false});
                if (ev && ev.r === 'ok') {
                    msg_field.val('');
                } else {
                }
            });
        });
        $('#open_icon_file_button').click(function() {
            $('#icon_input').change(function(){
                var file = $(this).prop('files')[0];
                var reader = new FileReader();
                reader.onload = function() {
                    $('#config_icon_preview').attr('src', reader.result);
                };
                reader.readAsDataURL(file);
            });
            $('#icon_input').click();
        });
        $(window).resize(function() {
            $('#msg_container').css('margin-top', post_container.outerHeight(true));
            ws_status.height(post_container.outerHeight(true));
            ws_status_msg.css('top', ((post_container.outerHeight(true) - ws_status_msg.outerHeight(true)) / 2) + 'px');
            ws_status_msg.css('left', ((post_container.outerWidth(true) - ws_status_msg.outerWidth(true)) / 2) + 'px');
        });
        msg_field.keypress(function(event) {
            if (event.which == 13) {
                post_button.click();
                event.preventDefault();
                return;
            }
        });

        change_ws_status(false);
        open_socket();
        $(window).resize();

        msg_field.focus();

        // TODO: レイアウト問題に対処するためのおまじない...
        window.setTimeout(function() { $(window).resize(); }, 1);
        window.setTimeout(function() { $(window).resize(); }, 10);
        window.setTimeout(function() { $(window).resize(); }, 100);
        window.setTimeout(function() { $(window).resize(); }, 1000);
    });
}) (this);
