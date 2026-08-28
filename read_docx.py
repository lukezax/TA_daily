import textract

# 读取888.docx文件
text_888 = textract.process('888.docx', encoding='utf-8')

print("888.docx内容：")
print("=" * 50)
print(text_888.decode('utf-8'))

print("\n" + "=" * 50)

# 读取智兔API文档.docx文件
text_api = textract.process('智兔API文档.docx', encoding='utf-8')

print("智兔API文档.docx内容：")
print("=" * 50)
print(text_api.decode('utf-8'))
