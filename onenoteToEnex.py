import email, os, sys, argparse, re, operator, codecs, base64, glob
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from mako.template import Template

args = None
attr_whitelist = ["src", "alt", "height", "width", "type", "title", "summary", "href", "rel"] # "value"
done = {}

class Note:
    def __init__(self, title, created, contents, updated=None):
        self.title = title
        self.contents = contents
        self.labels = []
        if args.addLabel:
            labels = args.addLabel.split(",")
            self.labels = labels
        self.created = created
        self.updated = updated or created
        self.author = args.author

    def __str__(self):
        return "%s - %s" % (self.title, self.datestamp)

    def __repr__(self):
        return "%s - %s" % (self.title, self.datestamp)

    def to_stamp(self, datetime):
        return datetime.strftime("%Y%m%dT%H%M%SZ")

    def to_html(self, heading="h2"):
        return Template("""
<div>
<${heading}>${note.title}</${heading}>
<div>${note.contents}</div>
</div>""").render(note=self, heading=heading)

    def to_enex(self):
        enexXML = Template("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export4.dtd">
<en-export application="Evernote" version="Evernote">
    <note>
        <title>${note.title}</title>
        <created>${note.to_stamp(note.created)}</created>
        <updated>${note.to_stamp(note.updated)}</updated>
        <note-attributes>
            <author>${note.author}</author>
        </note-attributes>
        % for label in note.labels:
        <tag>${label}</tag>
        % endfor
        <content>
            <![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
            <!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">
            <en-note>
                <div>${note.contents}</div>
            </en-note>
            ]]>
        </content>
    </note>
</en-export>
""")
        return enexXML.render(note=self)

def normalize_style(style):
    style = whitespace(style)
    new_style = []
    if "bold" in style:
        new_style.append("font-weight: bold")
    if "italic" in style:
        new_style.append("font-style: italic")
    if "underline" in style:
        new_style.append("text-decoration: underline")

    return ";".join(new_style)

def strip_attrs(nodes):
    # global args, attr_whitelist, done

    if nodes and len(nodes) > 0:
        for node in nodes:
            if is_element(node):
                style = node.attrs.get("style")
                attrs = node.attrs.items()
                node.attrs = {}

                for key, value in attrs:
                    if key in attr_whitelist:
                        node.attrs[key] = whitespace(value)
                    if key not in done:
                        done[key] = True
                        # print("has key: key)
                        # print(node.prettify())

                if style:
                    if args.keepStyle:
                        node.attrs["style"] = whitespace(style)
                    else:
                        node.attrs["style"] = normalize_style(style)

                strip_attrs(node.findAll())

def whitespace(text):
    wreg = r'[\n\r ]+'
    return re.sub(wreg, " ", (text or "").strip())

def is_element(node):
    return node and node.name is not None

def html_to_notes(html, media=[]):

    soup = BeautifulSoup(html, "html.parser")
    notes = []
    index = 0

    for child in soup.html.body.children:
        if child.name == "div":
            try:
                base = [c for c in child.children if c.name is not None][0]
                [title_node, date_node, *contents] = [c for c in base.contents if is_element(c)]

                title = whitespace(title_node.get_text())
                if len(contents) <= 0:
                    print("no contents: %i-%s" % (index, title))
                date = whitespace(date_node.get_text().strip())
                dtime = datetime.strptime(date, '%A, %B %d, %Y %I:%M %p').astimezone(timezone.utc)
                html = ""

                strip_attrs(contents)

                if len(media) > 0:
                    elements = base.findAll(src=True)
                    for element in elements:
                        src = os.path.basename(element.attrs.get("src"))
                        for m in media:
                            name = os.path.basename(m.get("content-location"))
                            if name == src:
                                element.attrs["src"] = "data:" + m.get_content_type() + ";charset=urf-8;base64," + m.get_payload(decode=False)
                                break

                html = whitespace("".join([n.prettify() for n in contents]))
                note = Note(title, dtime, html)
                notes.append(note)
                index += 1
            except Exception as e:
                print("ERROR in section", index)
                print(e)

    if args.sort:
        notes.sort(key=operator.attrgetter(args.sort))
    else:
        print("skip sort")

    print("total: #%s" % str(index))
    return notes

def get_dates(notes):
    dtimes = [n.created for n in notes]
    dtimes.sort()
    created = dtimes[0]
    dtimes = [n.updated for n in notes]
    dtimes.sort(reverse=True)
    updated = dtimes[0]
    return [created, updated]

def mht_to_html(mht_file_path):
    name = os.path.splitext(os.path.basename(mht_file_path))[0]
    dir_path = os.path.dirname(mht_file_path)
    html_file_path = os.path.join(dir_path, name + ".html")

    print("name:", name)
    print("dir path:", dir_path)
    print("html file path:", html_file_path)
    notes = []

    with open(mht_file_path, "rb") as mht_file:
        msg = email.message_from_bytes(mht_file.read())
        if msg.is_multipart():
            htmls = []
            media = []
            for part in msg.get_payload():
                if part.get_content_type() == "text/html":
                    htmls.append(part.get_payload(decode=True))
                else:
                    print("has media", part.get_content_type(), part.get("content-location"))
                    media.append(part)

            if len(htmls) > 1:
                print("multiple html parts!!!!")
            else:
                notes = html_to_notes(htmls[0], media)
        else:
            notes = html_to_notes(msg.get_payload(decode=True))

    if args.singleEnex:
        outpath = os.path.join(dir_path, name + ".enex")
        print(outpath)
        html = "".join([note.to_html(heading="h2" if len(note.contents) > 0 else "h1") for note in notes])
        [created, updated] = get_dates(notes)
        note = Note(name, created, html, updated)
        with codecs.open(outpath, 'w', 'utf-8') as outfile:
            outfile.write(note.to_enex())
        print("finished '%s'" % outpath)
    else:
        outpath = os.path.join(dir_path, "Evernote_Files_" + name)
        print("outpath:", outpath)
        try:
            os.mkdir(outpath)
        except Exception as e:
            print(e)

        for i, note in enumerate(notes):
            outfname = os.path.join(outpath, str(i + 1) + ".enex")
            # print(outfname, i)
            xml = note.to_enex()
            with codecs.open(outfname, 'w', 'utf-8') as outfile:
                outfile.write(xml)
        print("finished '%s' - %i enex files created" % (mht_file_path, len(notes)))

def getArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("mht_dir_path")
    parser.add_argument("--author", default="Anonymous")
    parser.add_argument("--addLabel", default=None)
    parser.add_argument("--keepStyle", default=False)
    parser.add_argument("--singleEnex", default=False)
    parser.add_argument("--sort", default="datetime")
    return parser.parse_args()

def main():
    global args
    args = getArgs()

    print(vars(args))

    # TODO: get mht files
    for path in glob.glob(os.path.join(args.mht_dir_path, "*.mht")):
        try: 
            print("importing: ", path)
            mht_to_html(path)
        except Exception as e:
            print("error importing %s" % path)
            print(e)

    print("attributes: ", list(done.keys()))
##    try:
##        mht_to_html(args.mht_dir_path)
##    except Exception as ex:
##        print("error!")
##        sys.exit(ex)

if __name__ == "__main__":
    main()
