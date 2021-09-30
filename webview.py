from flask import Flask
import os
import subprocess
from flask import Response, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from terraswap_swap_watch import run_terra_swap_price_watcher, get_luna_price_prices
from hodl import Terra

# I hope you are not reading this source! This "API" is really not ideal but it work!
# Apologies for this nasty laziness subprocess usage!
# Enjoy it!!

app = Flask(__name__)
hodl = Terra()

scheduler = BackgroundScheduler(daemon=True)
scheduler .add_job(hodl.is_loan_safe, 'interval', seconds=30)
# scheduler .add_job(process_notifications, 'interval', minutes=3)
scheduler .start()


@app.route('/')
def tail():
    info_log = []
    repay_log = []
    apscheduler_log = []
    page_tile = 'null'

    if os.path.exists('./logs/info.log'):
        arguments = ['tail', '-n', '10', './logs/info.log']
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        for line in iter(process.stdout.readline, b''):
            l = line.decode('utf-8')
            line = l.strip()
            info_log.append(line)

        # get the last "left to trigger"
        try:
            if 'Left until trigger: ' in info_log[-1]:
                page_title = info_log[-1].split()[7].strip(',')
            elif 'REPAYING' in info_log[-1]:
                page_title = 'REPAYING ...'
            else:
                page_title = '...'
        except IndexError:
            page_title = '...'
            pass

        if os.path.exists('./logs/repayments.log'):
            arguments = ['tail', '-n', '5', './logs/repayments.log']
            process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            for line in iter(process.stdout.readline, b''):
                l = line.decode('utf-8')
                line = l.strip()
                try:
                    url = line.split()[-1]
                    hlink = url
                    line = line.split(' TX')[0]
                except Exception as err:
                    hlink = 'err'
                    line = 'err'
                    url = 'err'
                    pass

                repay_log.append({'line': line, 'hlink': hlink})

        if os.path.exists('./logs/apscheduler.log'):
            arguments = ['tail', '-n', '5', './logs/apscheduler.log']
            process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            for line in iter(process.stdout.readline, b''):
                l = line.decode('utf-8')
                line = l.strip()
                apscheduler_log.append(line)

    else:
        return "Could not read info.log"

    terraswap_prices = run_terra_swap_price_watcher()

    luna_prices = get_luna_price_prices()

    # Reverse all lists ...
    info_log.reverse()
    repay_log.reverse()
    apscheduler_log.reverse()

    return render_template('index.html', title=page_title, buffer_list=info_log, repay_list=repay_log,
                           terraswap_prices=terraswap_prices, luna_price=luna_prices, apscheduler_list=apscheduler_log)
    # return Response(json.dumps(buffer),  mimetype='application/json')


if __name__ == '__main__':
    app.run()
