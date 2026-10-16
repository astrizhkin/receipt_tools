import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Split a receipt between N payers. Values (name/price/qty, the per-payer
/// split quantity, and the receipt total) are edited through dialogs; the
/// quantity total is derived (sum of line quantities). The split-quantity
/// dialog is a minus/number/plus
/// stepper (float-aware: non-integer line qty steps in max/10 increments).
/// Icons carry the color (blue add, red delete/remove); a line's price and
/// qty turn green/red when the line is correctly/incorrectly split.
/// The per-payer totals row is pinned under the column header.
class SplitPage extends StatefulWidget {
  final Map<String, dynamic> receipt;

  const SplitPage({super.key, required this.receipt});

  @override
  State<SplitPage> createState() => _SplitPageState();
}

class _SplitRow {
  String name;
  double price;
  double qty; // total quantity on the (possibly corrected) line
  List<double> splits; // quantity assigned to each payer

  _SplitRow(this.name, this.price, this.qty, this.splits);
}

class _SplitPageState extends State<SplitPage> {
  late final List<_SplitRow> _rows;
  late double _receiptTotal; // editable target from the physical receipt
  int _payers = 2;

  static const _wPos = 24.0;
  static const _wName = 150.0;
  static const _wPrice = 64.0;
  static const _wNum = 56.0; // qty, each payer split, actions: equal widths

  @override
  void initState() {
    super.initState();
    _receiptTotal = double.tryParse('${widget.receipt['total']}') ?? 0;
    _rows = [
      for (final item in (widget.receipt['items'] as List? ?? []))
        _SplitRow(
          '${item['name'] ?? ''}',
          double.tryParse('${item['price'] ?? 0}') ?? 0,
          double.tryParse('${item['qty'] ?? 0}') ?? 0,
          // growable: List.filled defaults to FIXED length, and add/removeAt
          // on payer add/remove threw UnsupportedError (dead buttons)
          List<double>.filled(_payers, 0, growable: true),
        ),
    ];
  }

  // ---- derived totals -------------------------------------------------------

  double get _itemsQty => _rows.fold(0.0, (s, r) => s + r.qty);
  double _payerTotal(int p) =>
      _rows.fold(0.0, (s, r) => s + r.price * r.splits[p]);
  double get _splitAmount =>
      List.generate(_payers, _payerTotal).fold(0.0, (s, v) => s + v);
  double get _splitQty =>
      _rows.fold(0.0, (s, r) => s + r.splits.fold(0.0, (a, b) => a + b));

  bool _lineOk(int i) =>
      (_rows[i].splits.fold(0.0, (a, b) => a + b) - _rows[i].qty).abs() < 0.005;

  static String _money(double v) => v.toStringAsFixed(2);
  static String _num(double v) =>
      v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(2);

  // ---- mutations ------------------------------------------------------------

  void _addPayer() => setState(() {
        _payers += 1;
        for (final r in _rows) {
          r.splits.add(0);
        }
      });

  void _removePayer(int p) => setState(() {
        _payers -= 1;
        for (final r in _rows) {
          r.splits.removeAt(p);
        }
      });

  void _addRow() => setState(() {
        _rows
            .add(_SplitRow('', 0, 0, List<double>.filled(_payers, 0, growable: true)));
      });

  void _deleteRow(int i) => setState(() => _rows.removeAt(i));

  // ---- editors (all dialogs) --------------------------------------------------

  Future<double?> _editNumber(String title, double current) async {
    final ctrl = TextEditingController(text: _num(current));
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Edit $title'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          keyboardType: TextInputType.number,
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Save')),
        ],
      ),
    );
    if (ok != true) return null;
    return double.tryParse(ctrl.text.replaceAll(',', '.'));
  }

  Future<void> _edit(int i, String field) async {
    final r = _rows[i];
    if (field == 'name') {
      final ctrl = TextEditingController(text: r.name);
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Edit name'),
          content: TextField(controller: ctrl, autofocus: true),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Cancel')),
            FilledButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Save')),
          ],
        ),
      );
      if (ok == true) setState(() => r.name = ctrl.text);
      return;
    }
    final isPrice = field == 'price';
    final v = await _editNumber(isPrice ? 'price' : 'quantity',
        isPrice ? r.price : r.qty);
    if (v != null) setState(() => isPrice ? r.price = v : r.qty = v);
  }

  Future<void> _editReceiptTotal() async {
    final v = await _editNumber('receipt total', _receiptTotal);
    if (v != null) setState(() => _receiptTotal = v);
  }

  /// Split-quantity editor: minus / number / plus, clamped to [0, line qty].
  /// Integer line qty steps by 1; a float line qty steps in qty/10 so the
  /// full range is 10 steps.
  Future<void> _editSplit(int row, int payer) async {
    final r = _rows[row];
    final max = r.qty;
    final step = max == max.roundToDouble() ? 1.0 : max / 10;
    var value = r.splits[payer];
    final saved = await showDialog<bool>(
      context: context,
      // non-dismissible barrier: a stray first tap (while the dialog is
      // still animating in) used to dismiss it instead of pressing plus
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: Text('Split quantity (0 – ${_num(max)})'),
          content: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton(
                color: Colors.red,
                iconSize: 32,
                icon: const Icon(Icons.remove_circle_outline),
                onPressed: () => setDlg(
                    () => value = (value - step).clamp(0.0, max).toDouble()),
              ),
              SizedBox(
                width: 70,
                child: Text(_num(value),
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                        fontSize: 20,
                        fontFeatures: [FontFeature.tabularFigures()])),
              ),
              IconButton(
                color: Colors.blue,
                iconSize: 32,
                icon: const Icon(Icons.add_circle_outline),
                onPressed: () => setDlg(
                    () => value = (value + step).clamp(0.0, max).toDouble()),
              ),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Cancel')),
            FilledButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Save')),
          ],
        ),
      ),
    );
    if (saved == true) setState(() => r.splits[payer] = value);
  }

  // ---- widgets ---------------------------------------------------------------

  Widget _editable(String text, VoidCallback onTap,
          {TextAlign align = TextAlign.left, Color color = Colors.black}) =>
      InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Text(text,
              textAlign: align,
              style: TextStyle(
                  fontSize: 13,
                  color: color,
                  decoration: TextDecoration.underline,
                  decorationColor: Colors.black26)),
        ),
      );

  Widget _cell(Widget child, double width) => SizedBox(
        width: width,
        child: child,
      );

  /// Full-cell icon button: the whole cell is the tap target, not just the
  /// icon glyph (small icons in wide cells felt dead before).
  Widget _iconCell(IconData icon, Color color, VoidCallback? onTap) =>
      InkWell(
        onTap: onTap,
        child: SizedBox(
          width: _wNum,
          height: 34,
          child: Center(child: Icon(icon, size: 22, color: color)),
        ),
      );

  Widget _headerText(String t, {TextAlign align = TextAlign.left}) =>
      Text(t,
          textAlign: align,
          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12));

  @override
  Widget build(BuildContext context) {
    final amountOk = (_splitAmount - _receiptTotal).abs() < 0.005;
    final qtyOk = (_splitQty - _itemsQty).abs() < 0.005;

    return Scaffold(
      appBar: AppBar(
        title: Text('Split — ${widget.receipt['store_name'] ?? ''}'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // target lines: editable receipt values + red/green split sums
            Row(
              children: [
                const Text('Receipt total: ',
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                _editable(_money(_receiptTotal), _editReceiptTotal),
                const SizedBox(width: 16),
                const Text('Split: ',
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                Text(_money(_splitAmount),
                    style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: amountOk ? Colors.green : Colors.red)),
              ],
            ),
            Row(
              children: [
                // quantity total is derived (sum of line quantities), not editable
                const Text('Quantity: ',
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                Text(_num(_itemsQty),
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w600)),
                const SizedBox(width: 16),
                const Text('Split: ',
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                Text(_num(_splitQty),
                    style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: qtyOk ? Colors.green : Colors.red)),
              ],
            ),
            const SizedBox(height: 8),
            // table: header + totals pinned, rows scroll vertically,
            // everything scrolls horizontally together (columns aligned).
            // The Item column absorbs slack so the table fills the viewport
            // (e.g. after rotation) and only scrolls when truly wider.
            Expanded(
              child: LayoutBuilder(builder: (context, vp) {
                final fixed =
                    _wPos + _wPrice + _wNum * (_payers + 2) + 20;
                final nameW = math.max(_wName, vp.maxWidth - fixed);
                return SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minWidth: vp.maxWidth),
                    child: Column(
                      children: [
                    // header
                    Row(
                      children: [
                        _cell(_headerText('#'), _wPos),
                        _cell(_headerText('Item'), nameW),
                        _cell(_headerText('Price', align: TextAlign.right), _wPrice),
                        _cell(_headerText('Qty', align: TextAlign.right), _wNum),
                        for (var p = 0; p < _payers; p++)
                          _cell(
                            _iconCell(Icons.person_remove, Colors.red,
                                _payers > 1 ? () => _removePayer(p) : null),
                            _wNum,
                          ),
                        _cell(
                            _iconCell(Icons.person_add, Colors.blue, _addPayer),
                            _wNum),
                      ],
                    ),
                    // pinned totals row, aligned to the columns
                    Row(
                      children: [
                        _cell(const SizedBox(), _wPos),
                        _cell(_headerText('Totals'), nameW),
                        _cell(const SizedBox(), _wPrice),
                        _cell(
                            Text(_num(_itemsQty),
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600, fontSize: 12),
                                textAlign: TextAlign.right),
                            _wNum),
                        for (var p = 0; p < _payers; p++)
                          _cell(
                              Text(_money(_payerTotal(p)),
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w600, fontSize: 12),
                                  textAlign: TextAlign.right),
                              _wNum),
                        _cell(const SizedBox(), _wNum),
                      ],
                    ),
                    const Divider(height: 12),
                    // rows
                    Expanded(
                      child: SingleChildScrollView(
                        child: Column(
                          children: [
                            for (var i = 0; i < _rows.length; i++) ...[
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.center,
                                children: [
                                  _cell(Text('${i + 1}',
                                      style: const TextStyle(fontSize: 13)),
                                      _wPos),
                                  _cell(
                                      _editable(
                                          _rows[i].name.isEmpty
                                              ? '—'
                                              : _rows[i].name,
                                          () => _edit(i, 'name')),
                                      nameW),
                                  _cell(
                                      _editable(_money(_rows[i].price),
                                          () => _edit(i, 'price'),
                                          align: TextAlign.right,
                                          color: _lineOk(i)
                                              ? Colors.green
                                              : Colors.red),
                                      _wPrice),
                                  _cell(
                                      _editable(_num(_rows[i].qty),
                                          () => _edit(i, 'qty'),
                                          align: TextAlign.right,
                                          color: _lineOk(i)
                                              ? Colors.green
                                              : Colors.red),
                                      _wNum),
                                  for (var p = 0; p < _payers; p++)
                                    _cell(
                                        _editable(_num(_rows[i].splits[p]),
                                            () => _editSplit(i, p),
                                            align: TextAlign.right),
                                        _wNum),
                                  _cell(
                                      _iconCell(Icons.delete_outline, Colors.red,
                                          () => _deleteRow(i)),
                                      _wNum),
                                ],
                              ),
                              const Divider(height: 10),
                            ],
                            // directly under the last row, inside the table
                            Align(
                              alignment: Alignment.centerLeft,
                              child: TextButton.icon(
                                onPressed: _addRow,
                                icon: const Icon(Icons.post_add,
                                    color: Colors.blue),
                                label: const Text('Add item'),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                      ],
                    ),
                  ),
                );
              }),
            ),
          ],
        ),
      ),
    );
  }
}
