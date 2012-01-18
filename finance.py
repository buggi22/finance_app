# imports
import sqlite3
import StringIO
import pylab
from flask import Flask, request, session, g, redirect, url_for, \
     abort, render_template, flash, make_response

# configuration
DATABASE = '/tmp/finance.db'
DEBUG = True
SECRET_KEY = 'development key'
USERNAME = 'admin'
PASSWORD = 'default'

app = Flask(__name__)
app.config.from_object(__name__)

app.config.from_envvar('FINANCE_APP_SETTINGS', silent=True)

def connect_db():
    return sqlite3.connect(app.config['DATABASE'])

@app.before_request
def before_request():
    g.db = connect_db()

@app.teardown_request
def teardown_request(exception):
    g.db.close()

def get_entries():
    cur = g.db.execute('select description, amountcents, srcbucketname, srcbucketid, destbucketname, destbucketid, entryid from entries_labeled')
    entries = [dict(description=row[0], amountstring=cents_to_string(row[1]), srcbucket=str(row[2]), srcbucketid=row[3], destbucket=str(row[4]), destbucketid=row[5], entryid=row[6]) for row in cur.fetchall()]

    cur = g.db.execute('select bucketid, bucketname, initialbalancecents from buckets where buckettype = "internal"')
    internals = [dict(bucketname=row[1], initialbalancecents=row[2], initialbalancestring=cents_to_string(row[2])) for row in cur.fetchall()]
    numinternals = len(internals)

    cur = g.db.execute('select entryid, bucketid_for_change, amountcents from entries_with_bucket_changes')
    runningtotals = [b['initialbalancecents'] for b in internals]

    for i, row in enumerate(cur.fetchall()):
        if(i % numinternals == 0):
            entries[i / numinternals]['internals'] = []
            entries[i / numinternals]['balances'] = []
        change_string = cents_to_string( int(row[2]) ) if row[2] <> 0 else "-"
        entries[i / numinternals]['internals'] += [ change_string ]
        runningtotals[i % numinternals] += row[2]
        entries[i / numinternals]['balances'] += [ cents_to_string( int(runningtotals[i % numinternals]) ) ]

    return (entries, internals)

@app.route('/')
def show_entries():
    entries, internals = get_entries()
    return render_template('show_entries.html', entries=entries, internals=internals)

@app.route('/add_entry', methods=['POST'])
def add_entry():
    if not session.get('logged_in'):
        abort(401)
    srcbucket  = bucketname_to_int(request.form['srcbucket'])
    destbucket = bucketname_to_int(request.form['destbucket'])
    g.db.execute('insert into entries (description, amountcents, srcbucket, destbucket) values (?, ?, ?, ?)',
            [request.form['description'], string_to_cents(request.form['amount']), srcbucket, destbucket ])
    g.db.commit()
    flash('New entry was successfully posted')
    return redirect(url_for('show_entries'))

@app.route('/show_buckets')
def show_buckets():
    cur = g.db.execute('select bucketname, initialbalancecents, net_change, finalbalancecents from buckets_with_net_change where buckettype = "internal" order by bucketid asc')
    buckets = [dict(name=row[0], initialbalancestring=cents_to_string(row[1]),
               netchangestring=cents_to_string(row[2]),
               finalbalancestring=cents_to_string(row[3]) )
               for row in cur.fetchall()]

    cur = g.db.execute('select bucketid, bucketname from buckets where buckettype = "proportion"')
    proportionnames = [row[1] for row in cur.fetchall()]
    numproportions = len(proportionnames)

    cur = g.db.execute('select percent from bucket_proportion_combos')
    i = 0
    row = cur.fetchone()
    while (row != None):
        if(i % numproportions == 0):
            buckets[i / numproportions]['proportions'] = []
        buckets[i / numproportions]['proportions'] += [row[0]]
        row = cur.fetchone()
        i += 1

    return render_template('show_buckets.html', buckets=buckets, proportionnames=proportionnames)

@app.route('/add_bucket', methods=['POST'])
def add_bucket():
    if not session.get('logged_in'):
        abort(401)
    g.db.execute('insert into buckets (bucketname, buckettype, initialbalancecents) values (?, "internal", ?)',
            [request.form['name'], string_to_cents(request.form['initialbalance'])])
    g.db.commit()
    flash('New bucket was successfully added')
    return redirect(url_for('show_buckets'))

@app.route('/history.png')
def history_png():
    entries, internals = get_entries()

    xvalues = pylab.arange(0, len(entries)+1, 1)
    yvalues = [[internal['initialbalancecents'] / 100.0] for internal in internals]

    for e in entries:
        for i, balance in enumerate(e['balances']):
            yvalues[i] += [string_to_cents(balance) / 100.0]

    series = []
    for yv in yvalues:
        series += [xvalues, yv]

    pylab.clf() # clear current figure
    pylab.plot(*series)
    seriesnames = [internal['bucketname'] for internal in internals]
    pylab.legend(seriesnames, 'lower right')

    imgdata = StringIO.StringIO()
    pylab.savefig(imgdata, format='png', dpi=80)
    imgdata.seek(0)

    response = make_response( imgdata.read() )
    response.mimetype = 'image/png'

    return response

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['username'] != app.config['USERNAME']:
            error = 'Invalid username'
        elif request.form['password'] != app.config['PASSWORD']:
            error = 'Invalid password'
        else:
            session['logged_in'] = True
            flash('You were logged in')
            return redirect(url_for('show_entries'))
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You were logged out')
    return redirect(url_for('show_entries'))

def bucketname_to_int(name):
    return g.db.execute('select bucketid from buckets where bucketname = ?', [name]) \
        .fetchall()[0][0]

def cents_to_string(cents):
    sign = ''
    if(cents == None):
        return 'None'
    elif(cents < 0):
        sign = '-'
    return sign + "$%d.%02d" % (int(abs(cents)/100), abs(cents) % 100)

def string_to_cents(s):
    multiplier = 1
    if(len(s) > 0 and s[0] == '-'):
        multiplier = -1
        s = s[1:]
    if(len(s) > 0 and s[0] == '$'):
        s = s[1:]
    cents = multiplier * int(float(s)*100)
    return cents

if __name__ == '__main__':
    app.run()
