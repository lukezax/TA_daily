import zipfile
import xml.etree.ElementTree as ET

# 读取docx文件并提取文本
def read_docx_text(docx_file):
    text = []
    try:
        with zipfile.ZipFile(docx_file, 'r') as zf:
            # 读取document.xml文件
            if 'word/document.xml' in zf.namelist():
                with zf.open('word/document.xml') as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    
                    # 查找所有文本节点
                    for elem in root.iter():
                        if elem.text and elem.text.strip():
                            text.append(elem.text.strip())
        return '\n'.join(text)
    except Exception as e:
        return f"Error reading {docx_file}: {str(e)}"

# 读取888.docx文件
print("888.docx内容：")
print("=" * 50)
text_888 = read_docx_text('888.docx')
print(text_888)

print("\n" + "=" * 50)

# 读取智兔API文档.docx文件
print("智兔API文档.docx内容（部分）：")
print("=" * 50)
text_api = read_docx_text('智兔API文档.docx')
# 只显示前1000个字符，避免输出过多
print(text_api[:1000] + "..." if len(text_api) > 1000 else text_api)
