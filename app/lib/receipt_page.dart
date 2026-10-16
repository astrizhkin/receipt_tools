import 'package:flutter/material.dart';

import 'api.dart';
import 'ocr_page.dart';
import 'split_page.dart';

class ReceiptPage extends StatefulWidget {
  final ApiClient api;
  final int receiptId;
  final String title;

  const ReceiptPage(
      {super.key, required this.api, required this.receiptId, this.title = ''});

  @override
  State<ReceiptPage> createState() => _ReceiptPageState();
}

class _ReceiptPageState extends State<ReceiptPage> {
  final ScrollController _scrollCtrl = ScrollController();
  Map<String, dynamic>? _receipt;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _scrollCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.getReceipt(widget.receiptId);
      setState(() => _receipt = r);
    } catch (e) {
      setState(() => _error = '$e');
    }
  }

  String _fmt(Object? v) => v == null ? '—' : '$v';

  static const _nameStyle = TextStyle(fontSize: 13);
  static const _numStyle = TextStyle(fontSize: 13, fontFeatures: [FontFeature.tabularFigures()]);
  static const _headStyle = TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Colors.black54);

  /// One table row: narrow # column, wrapping item name, fixed-width numbers.
  Widget _row({
    required String pos,
    required String name,
    String qty = '',
    String price = '',
    String sum = '',
    bool header = false,
  }) {
    final style = header ? _headStyle : _nameStyle;
    final numStyle = header ? _headStyle : _numStyle;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 22, child: Text(pos, style: style)),
          Expanded(flex: 5, child: Text(name, style: style)),
          SizedBox(width: 38, child: Text(qty, style: numStyle, textAlign: TextAlign.right)),
          SizedBox(width: 58, child: Text(price, style: numStyle, textAlign: TextAlign.right)),
          SizedBox(width: 62, child: Text(sum, style: numStyle, textAlign: TextAlign.right)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final r = _receipt;
    return Scaffold(
      appBar: AppBar(
        title: Text(r?['store_name'] ??
            (widget.title.isEmpty ? 'Receipt #${widget.receiptId}' : widget.title)),
        actions: [
          if (r != null)
            PopupMenuButton<String>(
              onSelected: (v) {
                if (v == 'split') {
                  Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => SplitPage(receipt: r)),
                  );
                }
              },
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'split', child: Text('Split')),
              ],
            ),
        ],
      ),
      body: _error.isNotEmpty
          ? Center(child: Text(_error, style: const TextStyle(color: Colors.red)))
          : r == null
              ? const Center(child: CircularProgressIndicator())
              : Scrollbar(
                  controller: _scrollCtrl,
                  thumbVisibility: true,
                  child: ListView(
                    controller: _scrollCtrl,
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
                    children: [
                      // outer Row: [expandable left group][action]. The left
                      // group owns every pixel left of the action, so the
                      // action is flush right at any width (portrait AND
                      // landscape); inside it, date · total · badge flow and
                      // only the date may shrink — the price never truncates.
                      Row(
                        children: [
                          Expanded(
                            child: Row(
                              children: [
                                Flexible(
                                  child: Text(
                                    _fmt(r['receipt_date']),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                const Text('·', style: TextStyle(fontSize: 15, color: Colors.black38)),
                                const SizedBox(width: 8),
                                Text(
                                  '${_fmt(r['total'])} ${_fmt(r['currency'])}',
                                  maxLines: 1,
                                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                                ),
                                // server-computed sum check: do items +
                                // discounts reconcile to the total?
                                // (null = pre-feature row)
                                if (r['sum_verified'] != null) ...[
                                  const SizedBox(width: 6),
                                  Tooltip(
                                    message: r['sum_verified'] == true
                                        ? 'Sum verification passed'
                                        : 'Sum verification FAILED — numbers do not add up (OCR error?)',
                                    child: Icon(
                                      r['sum_verified'] == true
                                          ? Icons.verified
                                          : Icons.error,
                                      color: r['sum_verified'] == true
                                          ? Colors.green
                                          : Colors.red,
                                      size: 20,
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ),
                          if ((r['raw_markdown'] as String?)?.isNotEmpty ?? false)
                            IconButton(
                              icon: const Icon(Icons.article_outlined),
                              tooltip: 'OCR text',
                              visualDensity: VisualDensity.compact,
                              style: IconButton.styleFrom(
                                minimumSize: const Size(32, 32),
                                padding: EdgeInsets.zero,
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              ),
                              onPressed: () => Navigator.push(
                                context,
                                MaterialPageRoute(
                                  builder: (_) => OcrPage(
                                      text: r['raw_markdown'] as String),
                                ),
                              ),
                            ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      _row(pos: '#', name: 'Item', qty: 'Qty', price: 'Price', sum: 'Sum', header: true),
                      const Divider(height: 8),
                      for (final item in (r['items'] as List? ?? []))
                        _row(
                          pos: _fmt(item['position']),
                          name: _fmt(item['name']),
                          qty: _fmt(item['qty']),
                          price: _fmt(item['price']),
                          sum: _fmt(item['sum']),
                        ),
                    ],
                  ),
                ),
    );
  }
}
