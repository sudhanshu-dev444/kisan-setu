class ProductListing {
  final String listingId;
  final String sellerId;
  final String sellerName;
  final String sellerType;
  final String cropName;
  final String? cropVariety;
  final double quantityQuintals;
  final double pricePerQuintal;
  final String locationVillage;
  final String locationDistrict;
  final String locationState;
  final String status;
  final String? photoUrl;

  ProductListing({
    required this.listingId,
    required this.sellerId,
    required this.sellerName,
    required this.sellerType,
    required this.cropName,
    this.cropVariety,
    required this.quantityQuintals,
    required this.pricePerQuintal,
    required this.locationVillage,
    required this.locationDistrict,
    required this.locationState,
    required this.status,
    this.photoUrl,
  });

  factory ProductListing.fromJson(Map<String, dynamic> json) {
    return ProductListing(
      listingId: json['listing_id'] ?? '',
      sellerId: json['seller_id'] ?? '',
      sellerName: json['seller_name'] ?? '',
      sellerType: json['seller_type'] ?? 'farmer',
      cropName: json['crop_name'] ?? '',
      cropVariety: json['crop_variety'],
      quantityQuintals: (json['quantity_quintals'] ?? 0).toDouble(),
      pricePerQuintal: (json['price_per_quintal'] ?? 0).toDouble(),
      locationVillage: json['location_village'] ?? '',
      locationDistrict: json['location_district'] ?? '',
      locationState: json['location_state'] ?? '',
      status: json['status'] ?? 'ACTIVE',
      photoUrl: json['photo_url'],
    );
  }
}

class MarketplaceOrder {
  final String orderId;
  final String listingId;
  final String buyerName;
  final String sellerName;
  final String cropName;
  final double quantityQuintals;
  final double pricePerQuintal;
  final double totalAmount;
  final String status;
  final String paymentStatus;

  MarketplaceOrder({
    required this.orderId,
    required this.listingId,
    required this.buyerName,
    required this.sellerName,
    required this.cropName,
    required this.quantityQuintals,
    required this.pricePerQuintal,
    required this.totalAmount,
    required this.status,
    required this.paymentStatus,
  });

  factory MarketplaceOrder.fromJson(Map<String, dynamic> json) {
    return MarketplaceOrder(
      orderId: json['order_id'] ?? '',
      listingId: json['listing_id'] ?? '',
      buyerName: json['buyer_name'] ?? '',
      sellerName: json['seller_name'] ?? '',
      cropName: json['crop_name'] ?? '',
      quantityQuintals: (json['quantity_quintals'] ?? 0).toDouble(),
      pricePerQuintal: (json['price_per_quintal'] ?? 0).toDouble(),
      totalAmount: (json['total_amount'] ?? 0).toDouble(),
      status: json['status'] ?? '',
      paymentStatus: json['payment_status'] ?? '',
    );
  }
}

class SellerEarnings {
  final String sellerId;
  final int totalOrders;
  final double totalRevenue;
  final double paidAmount;
  final double pendingAmount;
  final double totalQuantitySold;

  SellerEarnings({
    required this.sellerId,
    required this.totalOrders,
    required this.totalRevenue,
    required this.paidAmount,
    required this.pendingAmount,
    required this.totalQuantitySold,
  });

  factory SellerEarnings.fromJson(Map<String, dynamic> json) {
    return SellerEarnings(
      sellerId: json['seller_id'] ?? '',
      totalOrders: json['total_orders'] ?? 0,
      totalRevenue: (json['total_revenue'] ?? 0).toDouble(),
      paidAmount: (json['paid_amount'] ?? 0).toDouble(),
      pendingAmount: (json['pending_amount'] ?? 0).toDouble(),
      totalQuantitySold: (json['total_quantity_sold'] ?? 0).toDouble(),
    );
  }
}
