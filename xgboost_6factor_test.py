# -*- coding: utf-8 -*-
from atrader import *
from atrader.enums import * 
import numpy as np
import pandas as pd
import datetime
import xgboost as xgb
from sklearn.model_selection import KFold, train_test_split, GridSearchCV
from sklearn.metrics import confusion_matrix, mean_squared_error
from sklearn.datasets import load_iris, load_digits, load_boston
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.model_selection import KFold,StratifiedKFold
from sklearn import metrics
from sklearn.preprocessing import StandardScaler
import warnings
from sklearn.metrics import accuracy_score

def init(context: Context):  
    set_backtest(initial_cash=1e6)
    context.faclist = ['MktValue',
                       'NegMktValue',
                       'LFLO',
                       'LINEARREG_INTERCEPT',
                       'HT_TRENDLINE',
                       'KAMA'
                       ]
    context.tarlist=get_code_list('hs300')
    reg_factor(context.faclist)
    reg_kdata(frequency='month', fre_num=1, adjust=False)
    context.ratio = 0.9    #初始权重设为0.9
    context.val_num = 1  # 测试1个月
    begin_date = '2016-03-31'
    end_date = '2019-03-31'
    context.cal=pd.Series(get_trading_days(market='sse', begin_date=begin_date, end_date=end_date))
    # get_trading_days()以列表的形式获取2016-03-31到2018-03-31的交易日期（包含2018-03-31）
    # len取其长度，作为后面获取factor的天数
    context.days = len(get_trading_days(market='sse', begin_date=begin_date, end_date=end_date))
    # 设置开仓的最大资金量
def on_data(context: Context): 

    print(context.now)
    # 实时模式返回当前本地时间, 回测模式返回当前回测时间
    now = context.now
    # begin_date1(每月1号), end_date1 相差一个月
    begin_date1=now.replace(day=1)

    if now.month==12:
        if now.year == 2016:
            end_date1=begin_date1.replace(year=2017).replace(month=1)
        if now.year == 2017:
            end_date1 = begin_date1.replace(year=2018).replace(month=1)
        if now.year == 2018:
            end_date1 = begin_date1.replace(year=2019).replace(month=1)
    else:
        end_date1=begin_date1.replace(month=(begin_date1.month+1))

    # call提取begin_date1与end_date1之间的时间
    cal1=context.cal[context.cal<end_date1]
    cal1=cal1[cal1>begin_date1]
    orderlist=get_order_info(order_list=())
    print(cal1)   # call为当前一个月的所有交易日
    # cal[-2:-1]为本月最后一个交易日
    if now<datetime.datetime(2017,4,30):   # 取2016-03-31 12个月后的日期开始交易，前11个月的数据用于训练，第13个月的为标签。如此滚动。
        pass
    else:
        if now<cal1.iloc[-2]:  # 日期小于本月交易日的倒数第二天
            # 查询当前价格进行止损，减小最大回撤的方式
            #price0=get_reg_kdata(reg_idx=context.reg_kdata[0], target_indices=(), length=1, fill_up=True, df=True)
            positions = context.account().positions 
            idx_long_list = positions.loc[positions['volume_long']>0,'target_idx']
            for idx in idx_long_list:
                #price_idx = price0.loc[price0['target_idx']==idx,'close']
                amount_long = positions['amount_long'].iloc[idx]   # 多头持仓金额
                fpnl_long = positions['fpnl_long'].iloc[idx]     # 多头持仓的浮动盈亏
                if -fpnl_long>amount_long*0.1:
                    # 全部卖出
                    order_volume(account_idx=0, target_idx=idx,
                             volume=int(positions['volume_long'].iloc[idx]),
                             side=2, position_effect=2, order_type=2, price=0)
                else:
                    pass
        else:
            
            # price， target_idx取值为0，1，2，3（代表不同的股票）
            price=get_reg_kdata(reg_idx=context.reg_kdata[0], target_indices=(), length=13, fill_up=True, df=True)  #获取13个月的price
            price = price[price['close']!=0]
            price['ret_month'] = price.groupby('target_idx')['close'].apply(lambda x:(x-x.shift())/x.shift())  # 在相同的target_idx内计算ret
            price.loc[price['ret_month']>=0.03,'label'] = 1    # 盈利率>3%, 标记为1
            price.loc[price['ret_month']<0.03,'label'] = 0     # 盈利率<3%, 标记为0
            price_month1 = price[['target_idx','time','ret_month','close','label']]
            print(price_month1)
            price_month1['month'] = price_month1['time'].apply(lambda x:int(str(x)[0:4]+str(x)[5:7]))  # 增加month列，201701，201702，只记录月份，不记录日时分秒
            price_month1['ret_nextmonth'] = price_month1.groupby('target_idx')['ret_month'].shift(-1)  # 添加下个月的盈利
            price_month1['label'] = price_month1.groupby('target_idx')['label'].shift(-1)   # 对应平移标签，因为ret_month计算的是本月的盈利

            # factor的注册频率默认为日频
            factor=get_reg_factor(reg_idx=context.reg_factor[0], target_indices=(), length=300, df=True)
            factor = factor.dropna(subset =['date'])   # 删除非法日期
            factor['code'] = factor['target_idx'].apply(lambda x:context.target_list[x])    # 将用0，1，2，3等表示的股票换成对应的股票代码
            factor['month'] = factor['date'].apply(lambda x:int(str(x)[0:4]+str(x)[5:7]))  # 增加month列，2017-01，2017-02，只记录月份，不记录日时分秒
            factor_name = factor['factor'].drop_duplicates().tolist()   # 以列表的形式取出因子名称
            # 将factor按['target_idx','month','factor']分组，分别取每组的最后一行
            # 即取出各股票每个月末的所有因子值
            factor_month = factor.groupby(['target_idx','month','factor']).apply(lambda x:x.iloc[-1])[['date','value']].reset_index()
            # 添加所有因子名作为新的列
            factor_month1 = factor_month.groupby(['target_idx','month']).apply(deal).reset_index()
            
            df = pd.merge(factor_month1,price_month1,on=['target_idx','month'],how='right')

            """
            训练集取最初到最后的前一个月，[:-1]
            测试集取最后一个月[-1]
            """
            train = df.groupby('target_idx').apply(lambda x: x.iloc[:-1 * context.val_num - 1])
            test = df.groupby('target_idx').apply(lambda x: x.iloc[-1 * context.val_num - 1:-1])
            scaler=StandardScaler()   # 标准化

            # 提取因子值train[factor_name]作为特征
            X_train = train[factor_name]
            X_train = X_train.fillna(0).values
            X_train = scaler.fit_transform(X_train)    # 因子标准化
            # 提取train['label']作为标签，
            # .fillna(0)NaN补0，
            # .values转化成array形式
            y_train = train['label'].fillna(0).values
            
            X_test = test[factor_name]
            y_test = test['label'].values
            X_test = X_test.fillna(0).values
            #X_test=scaler.fit_transform(X_test)      # 因子标准化
            X_test = scaler.transform(X_test)  # 因子标准化

            # 预测
            model = XGBClassifier().fit(X_train, y_train)
            y_pred = model.predict(X_test)
            y_pred1 = pd.DataFrame(y_pred,columns=['label'])
            idx_list = list(y_pred1[y_pred1['label']==1].index)
            print(idx_list)
            positions = context.account().positions 

            if len(idx_list)==0:   # 没有一只股票在标的池，则卖出全部股票
                for target_idx in positions.loc[positions['volume_long']>0,'target_idx'].astype(int):
                    order_volume(account_idx=0, target_idx=target_idx,
                             volume=int(positions['volume_long'].iloc[target_idx]),
                             side=2, position_effect=2, order_type=2, price=0)
            else:
                # 平不在标的池的股票
                for target_idx in positions.target_idx.astype(int):
                    if target_idx not in idx_list:
                        if positions['volume_long'].iloc[target_idx] > 0:
                            order_volume(account_idx=0, target_idx=target_idx,
                            volume=int(positions['volume_long'].iloc[target_idx]),
                            side=2, position_effect=2, order_type=2, price=0)

                # 获取股票的权重
                percent_b = context.ratio / len(idx_list)
                #print(percent_b)
                # 买在标的池中的股票
                for target_idx in idx_list:
                
                    order_target_percent(account_idx=0, target_idx=target_idx, target_percent=percent_b, side=1, order_type=2)

                print(positions.loc[positions['volume_long']>0,'code'].tolist())

def deal(df):
    factor_name = df['factor'].tolist()
    df1 = pd.DataFrame(columns = factor_name)
    for i in factor_name:
        df1[i] = df.loc[df['factor']==i,'value'].values
    return df1

if __name__ == "__main__":
    # 投资域
    begin_date = '2016-03-31'
    end_date = '2019-03-31'
    cal=get_trading_days(market='sse', begin_date=begin_date, end_date=end_date)
    warnings.filterwarnings("ignore")
    start = datetime.datetime.now()
    tarlist = get_code_list('hs300')

    a = run_backtest('XGBoost',target_list=tarlist['code'].tolist(),file_path='.', begin_date=begin_date,
               end_date=end_date,frequency='month', fq=1)
