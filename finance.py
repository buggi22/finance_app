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

def update_balances(balances, changes):
    if(len(balances) != len(changes)):
        raise Exception("balances must be same length as changes")

    result = []

    for i, bucket_balance in enumerate(balances):
        new_balance = changes[i]['amountcents'] + bucket_balance['balancecents']

    	result.append( {
            'bucketname': bucket_balance['bucketname'],
            'balancecents': new_balance,
            'balancestring': cents_to_string( new_balance )
        } )

    return result

def get_balances_at(datetime=None):
    cur = g.db.execute('select bucketid, bucketname, initialbalancecents from buckets where buckettype = "internal"')
    initial_balances = [
        dict(
            bucketname=row[1],
            balancecents=row[2],
            balancestring=cents_to_string(row[2])
        ) for row in cur.fetchall() ]

    if(datetime == None):
        return initial_balances

    balances = [] + initial_balances
    
    list_of_changes = get_changes_by_entry_and_bucket(start=None, end=datetime)
    for changes in list_of_changes:
        balances = update_balances(balances, changes)

    return balances

def rangeDateQuery(baseQuery, start, end):
    if start == None and end == None:
        cur = g.db.execute(baseQuery)
    elif start == None:
        cur = g.db.execute(baseQuery + ' where date <= ?', [end])
    elif end == None:
        cur = g.db.execute(baseQuery + ' where date >= ?', [start])
    else:
        cur = g.db.execute(baseQuery + ' where date >= ? and date <= ?',
                           [start, end])
    return cur

def get_changes_by_entry_and_bucket(start=None, end=None):
    cur = rangeDateQuery('select entryid, bucketid_for_change, amountcents, date from entries_with_bucket_changes',
        start, end)

    rows = cur.fetchall()

    prev_entryid = None
    result = []

    for row in rows:
        if(row[0] != prev_entryid):
            result.append( [] )
        result[-1].append( dict(
            amountcents = row[2],
            amountstring = cents_to_string(int(row[2])) if row[2] != 0 else '-'
        ) )
        prev_entryid = row[0]

    return result

def get_ending_balances_by_entry_and_bucket(start=None, end=None):
    balances = get_balances_at(start)
    result = []
    list_of_changes = get_changes_by_entry_and_bucket(start, end)

    for changes in list_of_changes:
        balances = update_balances(balances, changes)
        result.append(balances)

    return result

def get_entries(start=None, end=None):
    cur = rangeDateQuery('select description, amountcents, srcbucketname, srcbucketid, ' +
        'destbucketname, destbucketid, entryid, date from entries_labeled', start, end)

    entries = [ 
        dict(
            description=row[0],
            amountstring=cents_to_string(row[1]),
            srcbucket=str(row[2]),
            srcbucketid=row[3],
            destbucket=str(row[4]),
            destbucketid=row[5],
            entryid=row[6],
            datetime=row[7]
        ) for row in cur.fetchall() ]
    return entries

def get_entries_with_changes_and_balances(start=None, end=None):
    entries = get_entries(start, end)
    initial_balances = get_balances_at(start)
    changes = get_changes_by_entry_and_bucket(start, end)
    balances = get_ending_balances_by_entry_and_bucket(start, end)

    for i in range(len(entries)):
        entries[i]['balances'] = balances[i]
        entries[i]['changes'] = changes[i]

    return (entries, initial_balances)

@app.route('/')
@app.route('/show_entries')
def show_entries():
    start = request.args.get('start', None)
    end = request.args.get('end', None)

    history_img_url = url_for('history_png', start=start, end=end)

    entries, initial_balances = get_entries_with_changes_and_balances(start, end)
    return render_template('show_entries.html', entries=entries,
                           initial_balances=initial_balances, start=start, end=end,
                           history_img_url=history_img_url)

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
    cur = g.db.execute('select bucketname, initialbalancecents, net_change, finalbalancecents from ' +
        'buckets_with_net_change where buckettype = "internal" order by bucketid asc')
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
    start = request.args.get('start', None)
    end = request.args.get('end', None)

    entries, initial_balances = get_entries_with_changes_and_balances(start, end)

    xvalues = pylab.arange(0, len(entries)+1, 1)
    yvalues = [[initial_balance['balancecents'] / 100.0] for initial_balance in initial_balances]
    seriesnames = [initial_balance['bucketname'] for initial_balance in initial_balances]

    for e in entries:
        for i, balance in enumerate(e['balances']):
            yvalues[i] += [ balance['balancecents'] / 100.0]

    series = []
    for yv in yvalues:
        series += [xvalues, yv]

    pylab.clf() # clear current figure
    pylab.plot(*series)
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
