<!-- `{{paper_name}}` 由 library/scripts/generate_paper_files.py 替换为命令行传入的 paper stem。 -->

## Initialize Paper Reading
Read the paper PDF in `library/pdf` using skills in .agents. If the paper record already exists under `library/papers`, reuse it.

The paper name is {{paper_name}}

## Enhance Chapter-based Reading
Enhance chapter-based reading content using the source text.

## Answer Questions
基于我已经生成的 {{paper_name}} 的内容和阅读笔记，回答我的问题。
- 请包含 `library/papers/{{paper_name}}/` 下相关的 record 文件和笔记，并使用它们来回答问题。
- 优先使用 `library/papers/{{paper_name}}/paper.json`、`note.md`、`fulltext.md`、`fulltext.zh-CN.md` 和 `assets/manifest.json`。
- 如果准备好了，请输出你包含在上下文中的相关文件列表，并告诉我你准备好了。
- 对于我接下来提出的问题，请在回答后将 Q&A 记录到对于笔记文件的 Q&A 章节下，对于没有 Q&A 章节的笔记文件，请创建一个 Q&A 章节并记录 Q&A。记录的内容须与对话内容保持一致，仅调整格式。
