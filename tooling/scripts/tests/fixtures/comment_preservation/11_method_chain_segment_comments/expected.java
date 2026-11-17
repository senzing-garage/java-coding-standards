public class Demo
{
    void build(Builder builder)
    {
        JsonObject task = Json.createObjectBuilder()
                              .add("str", "str1")  // Single value
                              .add("str2", "str3")  // Adds sub-list
                              .build();
        builder.add(KEY_ONE, 50)  // Short delay
               // Missing other properties
               .add(KEY_THREE, 200)
               .build();
        builder.add(KEY_ONE, 50)  /* inline block */
               .add(KEY_TWO, 100)
               .build();
    }
}
