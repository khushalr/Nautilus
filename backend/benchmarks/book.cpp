// Same integer level-update/BBO component as benchmark.py; synthetic input only.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <map>
#include <tuple>
#include <vector>
int main() {
    std::vector<std::tuple<int,long long,long long>> rows;
    int side; long long price, quantity;
    while (std::cin >> side >> price >> quantity) rows.emplace_back(side,price,quantity);
    if (rows.empty()) return 1;
    std::map<long long,long long> bids{{100000,1}}, asks{{100100,1}};
    std::vector<long long> latency;
    long long checksum=0;
    for (const auto& row: rows) {
        auto start=std::chrono::steady_clock::now();
        auto [s,p,q]=row;
        auto& book=s==0?bids:asks;
        if(q) book[p]=q; else book.erase(p);
        if(bids.empty() || asks.empty()) return 2;
        checksum += bids.rbegin()->first + asks.begin()->first;
        latency.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now()-start).count());
    }
    std::sort(latency.begin(),latency.end());
    auto percentile=[&](double p) {return latency[static_cast<size_t>(std::ceil(latency.size()*p))-1];};
    std::cout << "{\"checksum\":" << checksum << ",\"events\":" << rows.size()
              << ",\"p50_ns\":" << percentile(.50) << ",\"p95_ns\":" << percentile(.95)
              << ",\"p99_ns\":" << percentile(.99) << "}\n";
}
