import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

/// Raw OCR Markdown of a receipt (the VL model output stored server-side),
/// rendered with flutter_markdown_plus; SelectionArea keeps it copyable.
class OcrPage extends StatelessWidget {
  final String text;

  const OcrPage({super.key, required this.text});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('OCR text')),
      body: Scrollbar(
        thumbVisibility: true,
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          child: SelectionArea(
            child: MarkdownBody(
              data: text,
              selectable: false, // SelectionArea above handles selection
              // monospace keeps the receipt's printed columns aligned; the
              // renderer still styles any real markdown the OCR emits
              styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context))
                  .copyWith(
                p: const TextStyle(
                    fontFamily: 'monospace', fontSize: 13, height: 1.45),
                blockSpacing: 6,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
